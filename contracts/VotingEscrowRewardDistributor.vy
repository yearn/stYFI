# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Voting Escrow Reward Distributor
@author Yearn Finance
@license GNU AGPLv3
@notice A component to the RewardDistributor. It tracks migrated veYFI positions and reports
        the total weight (with decaying boost) as its reward weight.
        Rewards are claimed from the distributor as they become available and streamed over the
        following epoch to all positions proportional to their weight, determined by the 
        duration of their lock at time of snapshot.
"""

from ethereum.ercs import IERC20

interface ISnapshot:
    def locked(_account: address) -> Lock: view

interface IComponent:
    def sync_total_weight(_epoch: uint256) -> uint256: nonpayable

interface IDistributor:
    def claim() -> (uint256, uint256, uint256): nonpayable

implements: IComponent

struct Scale:
    numerator: uint256
    denominator: uint256

struct Lock:
    amount: uint256
    boost_epochs: uint256
    unlock_time: uint256

struct Unlock:
    amount: uint256
    slope_change: uint256

struct Weight:
    weight: uint256
    slope: uint256

genesis: public(immutable(uint256))
token: public(immutable(IERC20))
management: public(address)
pending_management: public(address)

snapshot: public(ISnapshot)
distributor: public(IDistributor)
weight_scale: public(Scale)
claimers: public(HashMap[address, bool])
reward_expiration: public(uint256)
reclaim_bounty: public(uint256)
reclaim_recipient: public(address)
report_bounty: public(uint256)
report_recipient: public(address)

last_epoch: public(uint256)
reward_epoch: public(uint256)
total_weights: public(HashMap[uint256, Weight]) # epoch => total weight
unlocks: public(HashMap[uint256, Unlock]) # epoch => unlock
rewards: public(HashMap[uint256, uint256]) # epoch => rewards

locks: public(HashMap[address, Lock]) # account => lock
last_claimed: public(HashMap[address, uint256]) # account => last claim time

event Migrate:
    account: indexed(address)
    unlock_epoch: uint256
    amount: uint256

event Claim:
    account: indexed(address)
    rewards: uint256

event Reclaim:
    caller: indexed(address)
    account: indexed(address)
    rewards: uint256
    bounty: uint256

event Report:
    caller: indexed(address)
    account: indexed(address)
    rewards: uint256
    bounty: uint256

event SetSnapshot:
    snapshot: address

event SetDistributor:
    distributor: address

event SetWeightScale:
    numerator: uint256
    denominator: uint256

event SetClaimer:
    account: address
    claimer: bool

event SetRewardExpiration:
    expiration: uint256
    bounty: uint256
    recipient: address

event SetReportBounty:
    bounty: uint256
    recipient: address

event PendingManagement:
    management: indexed(address)

event SetManagement:
    management: indexed(address)

EPOCH_LENGTH: constant(uint256) = 14 * 24 * 60 * 60
MAX_NUM_EPOCHS: constant(uint256) = 104
BOUNTY_PRECISION: constant(uint256) = 10_000

@deploy
def __init__(_genesis: uint256, _token: address):
    """
    @notice Constructor
    @param _genesis Genesis timestamp
    @param _token The address of the reward token
    """
    assert _genesis % EPOCH_LENGTH == 0
    
    genesis = _genesis
    token = IERC20(_token)
    self.management = msg.sender

    self.total_weights[0] = Weight(weight=10**12, slope=0)
    self.weight_scale = Scale(numerator=4, denominator=1)
    self.reward_expiration = 26
    self.reclaim_recipient = msg.sender
    self.report_recipient = msg.sender

@external
@view
def epoch() -> uint256:
    """
    @notice Query the current epoch number
    @return The current epoch number
    """
    return self._epoch()

@external
def sync_total_weight(_epoch: uint256) -> uint256:
    """
    @notice Compute and finalize the total weight for reward distribution purposes
    @param _epoch The epoch to compute the total weight for
    @return The total weight for this epoch
    """
    current: uint256 = self._epoch()
    assert _epoch <= current

    self._sync_total_weights(current)
    assert self.last_epoch >= _epoch

    scale: Scale = self.weight_scale
    return self.total_weights[_epoch].weight * scale.numerator // scale.denominator

@external
def migrate():
    """
    @notice Migrate a veYFI position
    """
    assert self.last_claimed[msg.sender] == 0
    current: uint256 = self._epoch()
    assert self._sync_total_weights(current)

    lock: Lock = staticcall self.snapshot.locked(msg.sender)
    amount: uint256 = lock.amount
    assert amount > 0

    unlock_epoch: uint256 = (lock.unlock_time - genesis) // EPOCH_LENGTH
    assert unlock_epoch > current and unlock_epoch < MAX_NUM_EPOCHS

    self.locks[msg.sender] = lock

    # add lock to total
    slope: uint256 = amount // MAX_NUM_EPOCHS
    self.total_weights[current].weight += amount + (lock.boost_epochs - current) * slope
    self.total_weights[current].slope += slope

    # schedule unlock
    self.unlocks[unlock_epoch].amount += amount + (lock.boost_epochs - unlock_epoch) * slope
    self.unlocks[unlock_epoch].slope_change += slope

    # set claim time to beginning of next epoch
    self.last_claimed[msg.sender] = genesis + (current + 1) * EPOCH_LENGTH

    log Migrate(account=msg.sender, unlock_epoch=unlock_epoch, amount=amount)

@external
def claim(_account: address) -> uint256:
    """
    @notice Claim rewards on behalf of an account
    @param _account Account to claim rewards for
    @return Amount of rewards tokens claimed
    """
    assert self.claimers[msg.sender]
    assert self._sync_rewards(self._epoch())

    rewards: uint256 = self._claim(_account, block.timestamp)
    if rewards > 0:
        assert extcall token.transfer(msg.sender, rewards, default_return_value=True)
        log Claim(account=_account, rewards=rewards)

    return rewards

@external
def reclaim(_account: address) -> (uint256, uint256):
    """
    @notice Reclaim expired rewards
    @param _account Account to reclaim rewards for
    @return Tuple with amount of rewards reclaimed and bounty amount received
    """
    assert self._sync_rewards(self._epoch())

    rewards: uint256 = self._claim(_account, block.timestamp - self.reward_expiration * EPOCH_LENGTH)
    bounty: uint256 = rewards * self.reclaim_bounty // BOUNTY_PRECISION
    if rewards > 0:
        log Reclaim(caller=msg.sender, account=_account, rewards=rewards, bounty=bounty)

    if bounty > 0:
        rewards -= bounty
        assert extcall token.transfer(msg.sender, bounty, default_return_value=True)

    if rewards > 0:
        assert extcall token.transfer(self.reclaim_recipient, rewards, default_return_value=True)

    return rewards, bounty

@external
def report(_account: address) -> (uint256, uint256):
    """
    @notice Report an early exit of a veYFI position
    @param _account Account to report
    @return Tuple with amount of rewards reclaimed and bounty amount received
    """
    epoch: uint256 = self._epoch()
    assert self._sync_rewards(epoch)

    # must be an active migrated account
    lock: Lock = self.locks[_account]
    assert lock.amount > 0
    unlock_epoch: uint256 = (lock.unlock_time - genesis) // EPOCH_LENGTH

    # must have early exited
    assert epoch < unlock_epoch
    snapshot: Lock = staticcall self.snapshot.locked(_account)
    assert snapshot.amount == 0

    # claim all rewards up until end of this epoch
    rewards: uint256 = self._claim(_account, genesis + (epoch + 1) * EPOCH_LENGTH)

    # zero out lock
    slope: uint256 = lock.amount // MAX_NUM_EPOCHS
    self.locks[_account].amount = 0
    self.total_weights[epoch].weight -= lock.amount + (lock.boost_epochs - epoch) * slope
    self.total_weights[epoch].slope -= slope
    self.unlocks[unlock_epoch].amount -= lock.amount + (lock.boost_epochs - unlock_epoch) * slope
    self.unlocks[unlock_epoch].slope_change -= slope

    bounty: uint256 = rewards * self.report_bounty // BOUNTY_PRECISION
    log Report(caller=msg.sender, account=_account, rewards=rewards, bounty=bounty)

    if bounty > 0:
        rewards -= bounty
        assert extcall token.transfer(msg.sender, bounty, default_return_value=True)

    if rewards > 0:
        assert extcall token.transfer(self.report_recipient, rewards, default_return_value=True)

    return rewards, bounty

@external
def sync_rewards() -> bool:
    """
    @notice Synchronize global rewards up until now
    @return True: rewards are fully synced, False: not fully synced
    """
    return self._sync_rewards(self._epoch())

@external
def set_snapshot(_snapshot: address):
    """
    @notice Set new snapshot address
    @param _snapshot Snapshot address
    @dev Can only be called by management
    @dev Caller is responsible for ensuring consistency between the old and new snapshot
    """
    assert msg.sender == self.management

    self.snapshot = ISnapshot(_snapshot)
    log SetSnapshot(snapshot=_snapshot)

@external
def set_distributor(_distributor: address):
    """
    @notice Set upstream reward distributor
    @param _distributor Distributor address
    @dev Can only be called by management
    """
    assert msg.sender == self.management

    self.distributor = IDistributor(_distributor)
    log SetDistributor(distributor=_distributor)

@external
def set_weight_scale(_numerator: uint256, _denominator: uint256):
    """
    @notice Set scale by which the total weight is multiplied
    @param _numerator Numerator
    @param _denominator Denominator
    @dev Can only be called by management
    """
    assert msg.sender == self.management
    assert _numerator > 0 and _denominator > 0

    self.weight_scale = Scale(numerator=_numerator, denominator=_denominator)
    log SetWeightScale(numerator=_numerator, denominator=_denominator)

@external
def set_claimer(_account: address, _claimer: bool):
    """
    @notice Whitelist account as reward claimer
    @param _account Account
    @param _claimer True: add to whitelist, False: remove from whitelist
    @dev Can only be called by management
    """
    assert msg.sender == self.management

    self.claimers[_account] = _claimer
    log SetClaimer(account=_account, claimer=_claimer)

@external
def set_reward_expiration(_expiration: uint256, _bounty: uint256, _recipient: address):
    """
    @notice Set reward expiration parameters
    @param _expiration Number of epochs after which rewards can be reclaimed
    @param _bounty Bounty (in bps) to give to the caller
    @param _recipient Recipient of the reclaimed rewards
    @dev Can only be called by management
    """
    assert msg.sender == self.management
    assert _expiration > 1
    assert _bounty <= BOUNTY_PRECISION
    assert _recipient != empty(address) or _bounty == BOUNTY_PRECISION

    self.reward_expiration = _expiration
    self.reclaim_bounty = _bounty
    self.reclaim_recipient = _recipient
    log SetRewardExpiration(expiration=_expiration, bounty=_bounty, recipient=_recipient)

@external
def set_report_bounty(_bounty: uint256, _recipient: address):
    """
    @notice Set report bounty parameters
    @param _bounty Bounty (in bps) to give to the caller
    @param _recipient Recipient of the reclaimed rewards
    @dev Can only be called by management
    """
    assert msg.sender == self.management
    assert _bounty <= BOUNTY_PRECISION
    assert _recipient != empty(address) or _bounty == BOUNTY_PRECISION

    self.report_bounty = _bounty
    self.report_recipient = _recipient
    log SetReportBounty(bounty=_bounty, recipient=_recipient)

@external
def set_management(_management: address):
    """
    @notice Set the pending management address.
            Needs to be accepted by that account separately to transfer management over
    @param _management New pending management address
    """
    assert msg.sender == self.management

    self.pending_management = _management
    log PendingManagement(management=_management)

@external
def accept_management():
    """
    @notice Accept management role.
            Can only be called by account previously marked as pending by current management
    """
    assert msg.sender == self.pending_management

    self.pending_management = empty(address)
    self.management = msg.sender
    log SetManagement(management=msg.sender)

@internal
@view
def _epoch() -> uint256:
    return unsafe_div(block.timestamp - genesis, EPOCH_LENGTH)

@internal
def _sync_total_weights(_current: uint256) -> bool:
    """
    @notice Compute total weights by consecutively applying the slope to the weight, 
            followed by applying the unlock to the weight and slope
    """
    last: uint256 = self.last_epoch
    if last == _current:
        return True

    weight: Weight = self.total_weights[last]
    for i: uint256 in range(32):
        last += 1

        # apply slope and unlocks
        unlock: Unlock = self.unlocks[last]
        weight.weight -= weight.slope + unlock.amount
        weight.slope -= unlock.slope_change

        self.total_weights[last] = weight

        if last == _current:
            break

    self.last_epoch = last
    return last == _current

@internal
def _sync_rewards(_current: uint256) -> bool:
    """
    @notice Sync epoch by epoch rewards by claiming from the distributor
    """
    epoch: uint256 = self.reward_epoch
    if epoch == _current:
        return True

    for i: uint256 in range(32):
        if epoch == _current:
            break
        self.rewards[epoch] = (extcall self.distributor.claim())[2]
        epoch += 1

    self.reward_epoch = epoch

    return epoch == _current

@internal
def _claim(_account: address, _time: uint256) -> uint256:
    """
    @notice Claim rewards for single account up until a specific timestamp.
            Rewards must be synced prior to calling
    """
    last_claimed: uint256 = self.last_claimed[_account]
    if last_claimed == 0 or last_claimed >= _time:
        return 0

    epoch: uint256 = (last_claimed - genesis) // EPOCH_LENGTH - 1
    completed_epoch: uint256 = (_time - genesis) // EPOCH_LENGTH - 1
    lock: Lock = self.locks[_account]
    if lock.amount == 0:
        self.last_claimed[_account] = _time
        return 0
    unlock_epoch: uint256 = (lock.unlock_time - genesis) // EPOCH_LENGTH

    weight: uint256 = lock.amount + lock.amount // MAX_NUM_EPOCHS * (lock.boost_epochs - epoch)
    epoch_rewards: uint256 = self.rewards[epoch] * weight // self.total_weights[epoch].weight

    rewards: uint256 = 0
    synced: bool = epoch == completed_epoch
    if not synced:
        # rollover to new epoch. first finalize the last one
        rewards += epoch_rewards - epoch_rewards * (last_claimed % EPOCH_LENGTH) // EPOCH_LENGTH

        for i: uint256 in range(32):
            epoch += 1

            if epoch == unlock_epoch:
                synced = True
                epoch_rewards = 0
                break

            weight = lock.amount + lock.amount // MAX_NUM_EPOCHS * (lock.boost_epochs - epoch)
            epoch_rewards = self.rewards[epoch] * weight // self.total_weights[epoch].weight
            synced = epoch == completed_epoch
            if synced:
                break
            else:
                rewards += epoch_rewards

        # partial sync is only allowed if we are reclaiming
        assert synced or _time < block.timestamp

        # set time to beginning of the epoch. only needs to be correct mod `EPOCH_LENGTH`
        last_claimed = 0

    if synced:
        rewards += epoch_rewards * (_time % EPOCH_LENGTH) // EPOCH_LENGTH - epoch_rewards * (last_claimed % EPOCH_LENGTH) // EPOCH_LENGTH
        self.last_claimed[_account] = _time

        # zero out expired lock
        if epoch == unlock_epoch:
            self.locks[_account].amount = 0
    else:
        # not fully synced, but the last epoch is already added to the rewards,
        # so the claim time is one `EPOCH_LENGTH` bigger than you'd expect otherwise
        self.last_claimed[_account] = genesis + (epoch + 2) * EPOCH_LENGTH

    return rewards
