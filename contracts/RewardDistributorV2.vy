# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Reward Distributor V2 (Generic Aggregator)
@author Yearn Finance
@license GNU AGPLv3
@notice Generic reward aggregator. Holds ALL reward and weight state, while reporters
        implement component-specific logic and send computed weights through a single
        interface. Any component can be added/removed without disrupting historical state.
"""

from ethereum.ercs import IERC20

struct StreamState:
    timestamp: uint256
    rewards: uint256

interface IConfigHub:
    def genesis() -> uint256: view
    def reward_token() -> IERC20: view
    def epoch() -> uint256: view
    def is_allowed(_account: address) -> bool: view
    def is_blacklisted(_account: address) -> bool: view
    def num_components() -> uint256: view
    def is_component_enabled(_component_id: uint256) -> bool: view
    def get_weight_scale(_component_id: uint256) -> (uint256, uint256): view
    def get_component_params(_component_id: uint256) -> (uint256, uint256): view
    def get_reclaim_params() -> (uint256, uint256, address): view
    def get_report_params() -> (uint256, address): view

interface IReporter:
    def compute_weight(_account: address, _user_data: uint256, _epoch: uint256) -> uint256: view

interface IPull:
    def pull(_epoch: uint256) -> uint256: nonpayable
# Constants
EPOCH_LENGTH: constant(uint256) = 14 * 24 * 60 * 60
PRECISION: constant(uint256) = 10**30
BOUNTY_PRECISION: constant(uint256) = 10_000
MAX_COMPONENTS: constant(uint256) = 32
MAX_SYNC_ITERATIONS: constant(uint256) = 512
MAX_BATCH_SIZE: constant(uint256) = 64

# Immutables
config_hub: public(immutable(IConfigHub))
token: public(immutable(IERC20))
genesis: public(immutable(uint256))

# Epoch state
last_finalized_epoch: public(uint256)
epoch_rewards: public(HashMap[uint256, uint256])
epoch_total_weight: public(HashMap[uint256, uint256])

# Reward integral state
reward_integral_global: public(uint256)
reward_integral_snapshot: public(HashMap[uint256, uint256])
stream_state: public(StreamState)

# Account reward tracking
account_integral: public(HashMap[address, uint256])
pending_rewards: public(HashMap[address, uint256])

# Weights and component state (all stored here)
account_weight: public(HashMap[uint256, HashMap[address, uint256]])  # component => account => weight
component_total_weight: public(HashMap[uint256, uint256])            # component => current total weight
account_total_weight: public(HashMap[address, uint256])             # account => sum across components
account_user_data: public(HashMap[uint256, HashMap[address, uint256]])  # component => account => reporter-packed data

# Reporter registry
component_reporter: public(HashMap[uint256, address])

# Pull source
pull_source: public(IPull)

# Events
event FinalizeEpoch:
    epoch: indexed(uint256)
    total_weight: uint256
    rewards: uint256

event AddRewards:
    depositor: indexed(address)
    epoch: indexed(uint256)
    rewards: uint256

event ReportAccountWeight:
    component_id: indexed(uint256)
    account: indexed(address)
    weight: uint256
    user_data: uint256

event Claim:
    account: indexed(address)
    recipient: indexed(address)
    rewards: uint256

event Reclaim:
    caller: indexed(address)
    account: indexed(address)
    rewards: uint256
    bounty: uint256

event SetComponentReporter:
    component_id: indexed(uint256)
    reporter: address

event SetPullSource:
    pull_source: address


@deploy
def __init__(_config_hub: address):
    """
    @notice Constructor
    @param _config_hub Address of the ConfigHub contract
    """
    config_hub = IConfigHub(_config_hub)
    token = staticcall config_hub.reward_token()
    genesis = staticcall config_hub.genesis()


# ═══════════════════════════════════════════════════════════════════════════════
# VIEWS
# ═══════════════════════════════════════════════════════════════════════════════

@external
@view
def epoch() -> uint256:
    return self._epoch()


@external
@view
def claimable(_account: address) -> uint256:
    weight: uint256 = self.account_total_weight[_account]
    pending: uint256 = self.pending_rewards[_account]
    if weight > 0:
        integral: uint256 = self.reward_integral_global
        pending += (integral - self.account_integral[_account]) * weight // PRECISION
    return pending


@external
@view
def get_account_state(_component_id: uint256, _account: address) -> (uint256, uint256):
    """
    @notice Get stored weight and user_data for an account/component
    @return (weight, user_data)
    """
    return self.account_weight[_component_id][_account], self.account_user_data[_component_id][_account]


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTER INTERFACE (GENERIC)
# ═══════════════════════════════════════════════════════════════════════════════

@external
def report_account_state(_component_id: uint256, _account: address, _user_data: uint256):
    """
    @notice Set the current user_data for an account; distributor computes weight via reporter callback.
    @param _component_id Component ID
    @param _account Account being updated
    @param _user_data Reporter-defined packed data to persist
    """
    assert msg.sender == self.component_reporter[_component_id], "unauthorized"
    assert staticcall config_hub.is_component_enabled(_component_id), "component disabled"

    current_epoch: uint256 = self._epoch()
    assert self._sync(current_epoch)
    assert self._sync_integral()
    self._sync_account_integral(_account)

    old_weight: uint256 = self.account_weight[_component_id][_account]
    self.account_user_data[_component_id][_account] = _user_data

    new_weight: uint256 = self._compute_weight(_component_id, _account, _user_data, current_epoch)
    self.account_weight[_component_id][_account] = new_weight

    # Update totals
    self.account_total_weight[_account] = self.account_total_weight[_account] - old_weight + new_weight
    self.component_total_weight[_component_id] = self.component_total_weight[_component_id] - old_weight + new_weight
    # Keep current epoch total weight fresh
    current_epoch_total: uint256 = self.epoch_total_weight[current_epoch]
    current_epoch_total = current_epoch_total - old_weight + new_weight
    self.epoch_total_weight[current_epoch] = current_epoch_total

    log ReportAccountWeight(component_id=_component_id, account=_account, weight=new_weight, user_data=_user_data)


@external
def report_account_state_batch(
    _component_id: uint256,
    _accounts: DynArray[address, MAX_BATCH_SIZE],
    _user_data: DynArray[uint256, MAX_BATCH_SIZE]
):
    """
    @notice Batch set user data; distributor computes weight via reporter callback.
    """
    assert msg.sender == self.component_reporter[_component_id], "unauthorized"
    assert staticcall config_hub.is_component_enabled(_component_id), "component disabled"
    assert len(_accounts) == len(_user_data), "length mismatch"

    current_epoch: uint256 = self._epoch()
    assert self._sync(current_epoch)
    assert self._sync_integral()

    for i: uint256 in range(MAX_BATCH_SIZE):
        if i >= len(_accounts):
            break
        account: address = _accounts[i]
        data: uint256 = _user_data[i]

        self._sync_account_integral(account)

        old_weight: uint256 = self.account_weight[_component_id][account]
        self.account_user_data[_component_id][account] = data
        new_weight: uint256 = self._compute_weight(_component_id, account, data, current_epoch)

        self.account_weight[_component_id][account] = new_weight
        self.account_total_weight[account] = self.account_total_weight[account] - old_weight + new_weight
        self.component_total_weight[_component_id] = self.component_total_weight[_component_id] - old_weight + new_weight

        log ReportAccountWeight(component_id=_component_id, account=account, weight=new_weight, user_data=data)


# ═══════════════════════════════════════════════════════════════════════════════
# SYNC AND EPOCH FINALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

@external
def sync() -> bool:
    return self._sync(self._epoch())


@external
def deposit(_epoch: uint256, _amount: uint256):
    assert _epoch >= self._epoch(), "past epoch"
    assert _amount > 0, "zero amount"

    self.epoch_rewards[_epoch] += _amount
    assert extcall token.transferFrom(msg.sender, self, _amount, default_return_value=True)
    log AddRewards(depositor=msg.sender, epoch=_epoch, rewards=_amount)


@internal
def _sync(_current_epoch: uint256) -> bool:
    epoch: uint256 = self.last_finalized_epoch
    if epoch >= _current_epoch:
        return True

    pull: IPull = self.pull_source
    num_components: uint256 = staticcall config_hub.num_components()

    # Bound iterations to avoid excessive gas in a single call
    remaining: uint256 = _current_epoch - epoch
    iterations: uint256 = remaining
    if iterations > MAX_SYNC_ITERATIONS:
        iterations = MAX_SYNC_ITERATIONS

    for i: uint256 in range(MAX_SYNC_ITERATIONS):
        if i >= iterations:
            break

        # Compute total weight from current component totals
        total_weight: uint256 = 0
        for cid: uint256 in range(MAX_COMPONENTS):
            if cid >= num_components:
                break
            if staticcall config_hub.is_component_enabled(cid):
                total_weight += self.component_total_weight[cid]

        self.epoch_total_weight[epoch] = total_weight

        # Pull rewards
        if pull.address != empty(address):
            pulled: uint256 = extcall pull.pull(epoch)
            if pulled > 0:
                assert extcall token.transferFrom(pull.address, self, pulled, default_return_value=True)
                self.epoch_rewards[epoch] += pulled
                log AddRewards(depositor=pull.address, epoch=epoch, rewards=pulled)

        rewards: uint256 = self.epoch_rewards[epoch]

        # If no weight, roll rewards forward
        if total_weight == 0 and rewards > 0:
            self.epoch_rewards[epoch] = 0
            self.epoch_rewards[epoch + 1] += rewards
            log AddRewards(depositor=self, epoch=epoch + 1, rewards=rewards)
            rewards = 0

        # Update global integral and snapshot
        if total_weight > 0:
            increment: uint256 = rewards * PRECISION // total_weight
            self.reward_integral_global += increment
            self.reward_integral_snapshot[epoch] = self.reward_integral_global

        log FinalizeEpoch(epoch=epoch, total_weight=total_weight, rewards=rewards)
        epoch += 1

    self.last_finalized_epoch = epoch

    # Update streaming state for current epoch if fully synced
    if epoch == _current_epoch:
        self.stream_state = StreamState(
            timestamp=block.timestamp - genesis,
            rewards=self.epoch_rewards[_current_epoch]
        )

    return epoch >= _current_epoch


@internal
def _sync_integral() -> bool:
    current_epoch: uint256 = self._epoch()
    ss: StreamState = self.stream_state
    stream_epoch: uint256 = unsafe_div(ss.timestamp, EPOCH_LENGTH)

    if stream_epoch < current_epoch:
        return False  # need _sync first

    if ss.rewards == 0:
        return True

    total_weight: uint256 = self.epoch_total_weight[current_epoch]
    if total_weight == 0:
        return True

    last_streamed: uint256 = (ss.timestamp % EPOCH_LENGTH) * ss.rewards // EPOCH_LENGTH
    current_ts: uint256 = block.timestamp - genesis
    new_streamed: uint256 = (current_ts % EPOCH_LENGTH) * ss.rewards // EPOCH_LENGTH
    unlocked: uint256 = new_streamed - last_streamed

    if unlocked > 0:
        self.reward_integral_global += unlocked * PRECISION // total_weight

    self.stream_state.timestamp = current_ts
    return True


@internal
@view
def _compute_weight(_component_id: uint256, _account: address, _user_data: uint256, _epoch: uint256) -> uint256:
    """
    @notice Compute weight via reporter callback and apply config scale
    """
    reporter: IReporter = IReporter(self.component_reporter[_component_id])
    raw_weight: uint256 = staticcall reporter.compute_weight(_account, _user_data, _epoch)

    num: uint256 = 0
    den: uint256 = 0
    num, den = staticcall config_hub.get_weight_scale(_component_id)
    if den == 0:
        return raw_weight
    return raw_weight * num // den


@internal
def _sync_account_integral(_account: address) -> uint256:
    weight: uint256 = self.account_total_weight[_account]
    integral: uint256 = self.reward_integral_global
    pending: uint256 = self.pending_rewards[_account]

    if weight > 0:
        pending += (integral - self.account_integral[_account]) * weight // PRECISION
        self.pending_rewards[_account] = pending

    self.account_integral[_account] = integral
    return pending


@internal
def _refresh_account_weights(_account: address, _epoch: uint256):
    """
    @notice Recompute all component weights for an account using reporter callbacks.
    """
    num_components: uint256 = staticcall config_hub.num_components()

    for cid: uint256 in range(MAX_COMPONENTS):
        if cid >= num_components:
            break
        if not staticcall config_hub.is_component_enabled(cid):
            continue

        old_weight: uint256 = self.account_weight[cid][_account]
        data: uint256 = self.account_user_data[cid][_account]
        if data == 0 and old_weight == 0:
            continue

        new_weight: uint256 = self._compute_weight(cid, _account, data, _epoch)
        if new_weight == old_weight:
            continue

        self.account_weight[cid][_account] = new_weight
        self.account_total_weight[_account] = self.account_total_weight[_account] - old_weight + new_weight
        self.component_total_weight[cid] = self.component_total_weight[cid] - old_weight + new_weight
        self.epoch_total_weight[_epoch] = self.epoch_total_weight[_epoch] - old_weight + new_weight


# ═══════════════════════════════════════════════════════════════════════════════
# CLAIM / RECLAIM
# ═══════════════════════════════════════════════════════════════════════════════

@external
def claim(_recipient: address = msg.sender) -> uint256:
    account: address = msg.sender
    assert not staticcall config_hub.is_blacklisted(account), "blacklisted"

    assert self._sync(self._epoch())
    self._refresh_account_weights(account, self._epoch())
    assert self._sync_integral()
    pending: uint256 = self._sync_account_integral(account)

    if pending == 0:
        return 0

    self.pending_rewards[account] = 0
    assert extcall token.transfer(_recipient, pending, default_return_value=True)

    log Claim(account=account, recipient=_recipient, rewards=pending)
    return pending


@external
def reclaim(_account: address) -> (uint256, uint256):
    assert self._sync(self._epoch())
    self._refresh_account_weights(_account, self._epoch())
    assert self._sync_integral()

    weight: uint256 = self.account_total_weight[_account]
    if weight == 0:
        return 0, 0

    expiration_epochs: uint256 = 0
    bounty_bps: uint256 = 0
    recipient: address = empty(address)
    expiration_epochs, bounty_bps, recipient = staticcall config_hub.get_reclaim_params()

    current_epoch: uint256 = self._epoch()
    if current_epoch < expiration_epochs:
        return 0, 0

    expired_epoch: uint256 = current_epoch - expiration_epochs
    expired_integral: uint256 = self.reward_integral_snapshot[expired_epoch]
    account_int: uint256 = self.account_integral[_account]

    if account_int >= expired_integral:
        return 0, 0

    rewards: uint256 = (expired_integral - account_int) * weight // PRECISION
    self.account_integral[_account] = expired_integral

    bounty: uint256 = rewards * bounty_bps // BOUNTY_PRECISION
    remainder: uint256 = rewards - bounty

    if rewards > 0:
        log Reclaim(caller=msg.sender, account=_account, rewards=rewards, bounty=bounty)

    if bounty > 0:
        assert extcall token.transfer(msg.sender, bounty, default_return_value=True)

    if remainder > 0:
        assert extcall token.transfer(recipient, remainder, default_return_value=True)

    return rewards, bounty


@external
def report(_component_id: uint256, _account: address) -> (uint256, uint256):
    """
    @notice Report an account for a component (e.g., early exit) and redistribute pending
    @return (total redistributed, bounty)
    """
    assert self._sync(self._epoch())
    self._refresh_account_weights(_account, self._epoch())
    assert self._sync_integral()

    pending: uint256 = self._sync_account_integral(_account)

    weight: uint256 = self.account_weight[_component_id][_account]
    if weight == 0:
        return 0, 0

    self.account_weight[_component_id][_account] = 0
    self.account_total_weight[_account] -= weight
    self.component_total_weight[_component_id] -= weight
    self.epoch_total_weight[self._epoch()] -= weight

    bounty_bps: uint256 = 0
    recipient: address = empty(address)
    bounty_bps, recipient = staticcall config_hub.get_report_params()

    bounty: uint256 = pending * bounty_bps // BOUNTY_PRECISION
    remainder: uint256 = pending - bounty

    if pending > 0:
        self.pending_rewards[_account] = 0

    if bounty > 0:
        assert extcall token.transfer(msg.sender, bounty, default_return_value=True)
    if remainder > 0:
        assert extcall token.transfer(recipient, remainder, default_return_value=True)

    return pending, bounty


# ═══════════════════════════════════════════════════════════════════════════════
# MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@external
def set_component_reporter(_component_id: uint256, _reporter: address):
    assert staticcall config_hub.is_allowed(msg.sender), "unauthorized"
    self.component_reporter[_component_id] = _reporter
    log SetComponentReporter(component_id=_component_id, reporter=_reporter)


@external
def set_pull_source(_pull_source: address):
    assert staticcall config_hub.is_allowed(msg.sender), "unauthorized"
    self.pull_source = IPull(_pull_source)
    log SetPullSource(pull_source=_pull_source)


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

@internal
@view
def _epoch() -> uint256:
    return unsafe_div(block.timestamp - genesis, EPOCH_LENGTH)
