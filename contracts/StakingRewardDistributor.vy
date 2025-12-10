# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Staking Reward Distributor
@author Yearn Finance
@license GNU AGPLv3
@notice A component to the RewardDistributor. It tracks staking balances through the stYFI hook
        and snapshots the total staked balance each epoch to report as its reward weight.
        Rewards are claimed from the distributor as they become available and streamed over the
        following epoch to all stakers, proportional to their current balance.
"""

from ethereum.ercs import IERC20

interface IHooks:
    def on_transfer(_caller: address, _from: address, _to: address, _supply: uint256, _prev_staked_from: uint256, _prev_staked_to: uint256, _value: uint256): nonpayable
    def on_stake(_caller: address, _account: address, _prev_supply: uint256, _prev_staked: uint256, _value: uint256): nonpayable
    def on_unstake(_account: address, _prev_supply: uint256, _prev_staked: uint256, _value: uint256): nonpayable
    def instant_withdrawal(_account: address) -> bool: view

interface IComponent:
    def sync_total_weight(_epoch: uint256) -> uint256: nonpayable

interface IDistributor:
    def genesis() -> uint256: view
    def claim() -> (uint256, uint256, uint256): nonpayable

implements: IHooks
implements: IComponent

struct Scale:
    numerator: uint256
    denominator: uint256

struct Weight:
    epoch: uint256
    time: uint256
    weight: uint256

struct TotalWeight:
    epoch: uint256
    weight: uint256

struct Cursor:
    count: uint256
    last: uint256

struct Rewards:
    timestamp: uint256
    rewards: uint256

genesis: public(immutable(uint256))
token: public(immutable(IERC20))
management: public(address)
pending_management: public(address)

depositor: public(address)
staking: public(IERC20)
distributor: public(IDistributor)
weight_scale: public(Scale)
claimers: public(HashMap[address, bool])
reward_expiration: public(uint256)
reclaim_bounty: public(uint256)
reclaim_recipient: public(address)

total_weight_cursor: public(Cursor)
total_weight_entries: public(HashMap[uint256, TotalWeight]) # idx => epoch | weight

epoch_rewards: public(Rewards)
reward_integral: public(uint256)
reward_integral_snapshot: public(HashMap[uint256, uint256])
account_reward_integral: public(HashMap[address, uint256])
pending_rewards: public(HashMap[address, uint256])

event Claim:
    account: indexed(address)
    rewards: uint256

event Reclaim:
    caller: indexed(address)
    account: indexed(address)
    rewards: uint256
    bounty: uint256

event SetDepositor:
    depositor: indexed(address)

event SetStaking:
    staking: indexed(address)

event SetDistributor:
    distributor: indexed(address)

event SetWeightScale:
    numerator: uint256
    denominator: uint256

event SetClaimer:
    account: indexed(address)
    claimer: bool

event SetRewardExpiration:
    expiration: uint256
    bounty: uint256
    recipient: address

event PendingManagement:
    management: indexed(address)

event SetManagement:
    management: indexed(address)

EPOCH_LENGTH: constant(uint256) = 14 * 24 * 60 * 60
RAMP_LENGTH: constant(uint256) = 4 * EPOCH_LENGTH
INCREMENT: constant(bool) = True
DECREMENT: constant(bool) = False
PRECISION: constant(uint256) = 10**30
BOUNTY_PRECISION: constant(uint256) = 10_000

@deploy
def __init__(_distributor: address, _token: address):
    """
    @notice Constructor
    @param _distributor The distributor address
    @param _token The address of the reward token
    """
    genesis = staticcall IDistributor(_distributor).genesis()
    token = IERC20(_token)

    self.management = msg.sender
    self.distributor = IDistributor(_distributor)
    self.total_weight_cursor = Cursor(count=1, last=0)
    self.total_weight_entries[0] = TotalWeight(epoch=0, weight=10**12)
    self.weight_scale = Scale(numerator=4, denominator=1)
    self.reward_expiration = 26
    self.reclaim_recipient = msg.sender

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
    @dev Can only be called by the distributor
    """
    assert msg.sender == self.distributor.address
    cursor: Cursor = self.total_weight_cursor
    
    weight: uint256 = 0
    next_idx: uint256 = cursor.last + 1
    if next_idx == cursor.count:
        # already at last entry
        weight = self.total_weight_entries[cursor.last].weight
    else:
        # peek into next entry
        next: TotalWeight = self.total_weight_entries[next_idx]
        if _epoch < next.epoch:
            # next entry is for a future epoch, keep using current entry
            weight = self.total_weight_entries[cursor.last].weight
        else:
            # update cursor
            self.total_weight_cursor.last = next_idx

            weight = next.weight
    scale: Scale = self.weight_scale
    return weight * scale.numerator // scale.denominator

@external
def sync_rewards(_account: address = empty(address)) -> bool:
    """
    @notice Synchronize global rewards up until now
    @param _account Also update rewards for this specific account (optional)
    @return True: rewards are fully synced, False: not fully synced
    """
    synced: bool = self._sync_integral()
    if _account != empty(address):
        staked: uint256 = staticcall self.staking.balanceOf(_account)
        self._sync_account_integral(_account, staked)
    return synced

@external
def on_transfer(_caller: address, _from: address, _to: address, _supply: uint256, _prev_staked_from: uint256, _prev_staked_to: uint256, _amount: uint256):
    """
    @notice Triggered by the hook upon transfer of tokens
    @param _caller Originator of the transfer
    @param _from Sender of the token
    @param _to Recipient of the tokens
    @param _supply Total token supply
    @param _prev_staked_from Staked balance of sender before transfer
    @param _prev_staked_to Staked balance of recipient before transfer
    @param _amount Amount of tokens to transfer
    """
    assert msg.sender == self.depositor
    assert self._sync_integral()
    self._sync_account_integral(_from, _prev_staked_from)
    self._sync_account_integral(_to, _prev_staked_to)

@external
def on_stake(_caller: address, _account: address, _prev_supply: uint256, _prev_staked: uint256, _amount: uint256):
    """
    @notice Triggered by the hook upon staking of tokens
    @param _caller Originator of the tokens
    @param _account Recipient of the staked tokens
    @param _prev_supply Total token supply before stake
    @param _prev_staked Staked balance of recipient before stake
    @param _amount Amount of tokens to stake
    """
    assert msg.sender == self.depositor
    assert self._sync_integral()
    self._update_total_weight(_amount, INCREMENT)
    self._sync_account_integral(_account, _prev_staked)

@external
def on_unstake(_account: address, _prev_supply: uint256, _prev_staked: uint256, _amount: uint256):
    """
    @notice Triggered by the hook upon unstaking of tokens
    @param _account Originator of the staked tokens
    @param _prev_supply Total token supply before unstake
    @param _prev_staked Staked balance of originator before unstake
    @param _amount Amount of tokens to unstake
    """
    assert msg.sender == self.depositor
    assert self._sync_integral()
    self._update_total_weight(_amount, DECREMENT)
    self._sync_account_integral(_account, _prev_staked)

@external
@view
def instant_withdrawal(_account: address) -> bool:
    """
    @notice Query instant withdrawal status of an account
    @param _account Account to query withdrawal status for
    @return Always False
    """
    return False

@external
def claim(_account: address) -> uint256:
    """
    @notice Claim rewards on behalf of an account
    @param _account Account to claim rewards for
    @return Amount of rewards tokens claimed
    """
    staked: uint256 = staticcall self.staking.balanceOf(_account)
    if staked == 0 and self.pending_rewards[_account] == 0:
        # shortcut accounts that are guaranteed to have no rewards
        return 0

    assert self.claimers[msg.sender]
    assert self._sync_integral()
    pending: uint256 = self._sync_account_integral(_account, staked)

    if pending > 0:
        self.pending_rewards[_account] = 0
        assert extcall token.transfer(msg.sender, pending, default_return_value=True)
        log Claim(account=_account, rewards=pending)

    return pending

@external
def reclaim(_account: address) -> (uint256, uint256):
    """
    @notice Reclaim expired rewards
    @param _account Account to reclaim rewards for
    @return Tuple with amount of rewards reclaimed and bounty amount received
    """
    assert self._sync_integral()

    staked: uint256 = staticcall self.staking.balanceOf(_account)
    if staked == 0:
        return 0, 0

    epoch: uint256 = self._epoch() - self.reward_expiration
    integral: uint256 = self.reward_integral_snapshot[epoch]
    account_integral: uint256 = self.account_reward_integral[_account]
    if account_integral >= integral:
        return 0, 0

    rewards: uint256 = (integral - account_integral) * staked // PRECISION
    self.account_reward_integral[_account] = integral
    if rewards == 0:
        return 0, 0

    bounty: uint256 = rewards * self.reclaim_bounty // BOUNTY_PRECISION
    log Reclaim(caller=msg.sender, account=_account, rewards=rewards, bounty=bounty)

    if bounty > 0:
        rewards -= bounty
        assert extcall token.transfer(msg.sender, bounty, default_return_value=True)

    if rewards > 0:
        assert extcall token.transfer(self.reclaim_recipient, rewards, default_return_value=True)

    return rewards, bounty

@external
def set_depositor(_depositor: address):
    """
    @notice Set the depositor
    @param _depositor Depositor address
    @dev Can only be called by management
    @dev Caller is responsible for ensuring consistency between the old and new depositor
    """
    assert msg.sender == self.management

    self.depositor = _depositor
    log SetDepositor(depositor=_depositor)

@external
def set_staking(_staking: address):
    """
    @notice Set the staking address
    @param _staking Staking address
    @dev Can only be called by management
    @dev Caller is responsible for ensuring consistency between the depositor and staking contract
    """
    assert msg.sender == self.management

    self.staking = IERC20(_staking)
    log SetStaking(staking=_staking)

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
def _update_total_weight(_amount: uint256, _increment: bool):
    """
    @notice Increase or decrease the total weight.
            Global integral must be synced before calling
    """
    current_epoch: uint256 = self._epoch()

    # load latest total weight
    count: uint256 = self.total_weight_cursor.count
    idx: uint256 = count - 1
    weight: TotalWeight = self.total_weight_entries[idx]

    if current_epoch > weight.epoch:
        # new epoch, add entry to list
        idx = count
        weight.epoch = current_epoch
        self.total_weight_cursor.count = count + 1

    if _increment == INCREMENT:
        weight.weight += _amount
    else:
        weight.weight -= _amount

    self.total_weight_entries[idx] = weight

@internal
def _sync_integral() -> bool:
    """
    @notice Sync global integral to the latest value
    """
    current_epoch: uint256 = self._epoch()

    unlocked: uint256 = 0
    ew: Rewards = self.epoch_rewards
    epoch: uint256 = unsafe_div(ew.timestamp, EPOCH_LENGTH)
    synced: bool = epoch == current_epoch
    last_streamed: uint256 = (ew.timestamp % EPOCH_LENGTH) * ew.rewards // EPOCH_LENGTH
    ew.timestamp = block.timestamp - genesis
    total_weight: uint256 = self.total_weight_entries[self.total_weight_cursor.count - 1].weight
    integral: uint256 = self.reward_integral

    if not synced:
        # rollover to new epoch. first finalize the last one
        unlocked = ew.rewards - last_streamed
        last_streamed = 0

        # save integral snapshot
        self.reward_integral_snapshot[epoch] = integral + unlocked * PRECISION // total_weight

        # fast forward through any other completed epochs
        distributor: IDistributor = self.distributor
        epoch_rewards: uint256 = 0
        for i: uint256 in range(32):
            epoch += 1
            epoch_rewards = (extcall distributor.claim())[2]
            synced = epoch == current_epoch
            if synced:
                break
            else:
                unlocked += epoch_rewards
                self.reward_integral_snapshot[epoch] = integral + unlocked * PRECISION // total_weight

        if synced:
            # fully caught up
            ew.rewards = epoch_rewards
        else:
            # not fully caught up. we already added the full amount to `unlocked`, so we 
            # zero out the epoch rewards to not double count it in the next call
            ew.timestamp = epoch * EPOCH_LENGTH
            ew.rewards = 0

    self.epoch_rewards = ew

    streamed: uint256 = (ew.timestamp % EPOCH_LENGTH) * ew.rewards // EPOCH_LENGTH
    unlocked += streamed - last_streamed
    if unlocked == 0:
        return synced

    # update integral
    self.reward_integral = integral + unlocked * PRECISION // total_weight

    return synced

@internal
def _sync_account_integral(_account: address, _staked: uint256) -> uint256:
    """
    @notice Sync integral of a specific account to the latest value
    """
    integral: uint256 = self.reward_integral
    pending: uint256 = self.pending_rewards[_account]
    if _staked > 0:
        pending += (integral - self.account_reward_integral[_account]) * _staked // PRECISION
        self.pending_rewards[_account] = pending
    self.account_reward_integral[_account] = integral
    return pending
