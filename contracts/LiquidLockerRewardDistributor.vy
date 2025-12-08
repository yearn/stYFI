# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Liquid Locker Reward Distributor
@author Yearn Finance
@license GNU AGPLv3
@notice A component to the RewardDistributor. It tracks staking balances of LL tokens through their 
        hooks. It reports a total weight that is preconfigured and decays over time.
        Rewards are claimed from the distributor as they become available and streamed over the
        following epoch, proportional to each LL relative weight and each stakers current share.
"""

from ethereum.ercs import IERC20

interface IHooks:
    def on_stake(_caller: address, _account: address, _value: uint256): nonpayable
    def on_unstake(_account: address, _value: uint256): nonpayable

interface IComponent:
    def sync_total_weight(_epoch: uint256) -> uint256: nonpayable

interface IDistributor:
    def claim() -> (uint256, uint256, uint256): nonpayable

implements: IHooks
implements: IComponent

struct Scale:
    numerator: uint256
    denominator: uint256

struct Staked:
    epoch: uint256
    time: uint256
    amount: uint256

struct Rewards:
    timestamp: uint256
    rewards: uint256

genesis: public(immutable(uint256))
token: public(immutable(IERC20))
lock_duration: public(immutable(uint256))
management: public(address)
pending_management: public(address)

depositors: public(HashMap[address, uint256])
distributor: public(IDistributor)
weight_scale: public(Scale)
claimers: public(HashMap[address, bool])
reward_expiration: public(uint256)
reclaim_bounty: public(uint256)
reclaim_recipient: public(address)

total_unboosted_weight: public(uint256)
normalized_weights: public(uint256[3]) # ll idx => normalized weight

previous_total_staked: public(Staked[3])
total_staked: public(Staked[3])
previous_staked: public(HashMap[uint256, HashMap[address, Staked]])
staked: public(HashMap[uint256, HashMap[address, Staked]])

reward_epoch: public(uint256)
epoch_total_rewards: public(HashMap[uint256, uint256]) # epoch => total rewards
current_rewards: public(Rewards[3])
reward_integral: public(uint256[3])
reward_integral_snapshot: public(HashMap[uint256, HashMap[uint256, uint256]]) # ll idx => epoch => snapshot
account_reward_integral: public(HashMap[uint256, HashMap[address, uint256]]) # ll idx => account => integral
pending_rewards: public(HashMap[address, uint256]) # account => rewards

event Claim:
    account: indexed(address)
    rewards: uint256

event Reclaim:
    caller: indexed(address)
    account: indexed(address)
    idx: uint256
    rewards: uint256
    bounty: uint256

event SetDepositor:
    idx: indexed(uint256)
    depositor: address

event SetDistributor:
    distributor: address

event SetWeightScale:
    numerator: uint256
    denominator: uint256

event SetUnboostedWeights:
    weights: uint256[3]

event SetClaimer:
    account: address
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
BOOST_DURATION: constant(uint256) = 104

INCREMENT: constant(bool) = True
DECREMENT: constant(bool) = False
PRECISION: constant(uint256) = 10**30
NORM_WEIGHT_PRECISION: constant(uint256) = 10**18
BOUNTY_PRECISION: constant(uint256) = 10_000

@deploy
def __init__(_genesis: uint256, _token: address, _lock: uint256, _depositors: address[3]):
    """
    @notice Constructor
    @param _genesis Genesis timestamp
    @param _token The address of the reward token
    @param _lock The duration of the veYFI lock, in epochs
    @param _depositors Array with the address of each of the depositors
    """
    assert _genesis % EPOCH_LENGTH == 0
    assert _lock <= BOOST_DURATION

    genesis = _genesis
    token = IERC20(_token)
    lock_duration = _lock

    self.management = msg.sender

    for i: uint256 in range(3):
        d: address = _depositors[i]
        assert d != empty(address)
        assert self.depositors[d] == 0
        self.depositors[d] = i + 1
        self.total_staked[i] = Staked(epoch=0, time=0, amount=10**12)

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
    @notice Compute the total weight for reward distribution purposes
    @param _epoch The epoch to compute the total weight for
    @return The total weight for this epoch
    @dev Can only be called by the distributor
    """
    assert msg.sender == self.distributor.address

    if _epoch >= lock_duration:
        return 0

    weight: uint256 = self.total_unboosted_weight
    # changing the total weight requires all historical weights to be synced, 
    # so it is safe to just take the latest value here

    # apply boost
    weight += weight * (BOOST_DURATION - _epoch) // BOOST_DURATION

    scale: Scale = self.weight_scale
    return weight * scale.numerator // scale.denominator

@external
def on_stake(_caller: address, _account: address, _value: uint256):
    """
    @notice Triggered by a hook upon staking of LL tokens
    @param _caller Originator of the tokens
    @param _account Recipient of the staked tokens
    @param _value Amount of tokens to stake
    """
    idx: uint256 = self.depositors[msg.sender] - 1
    self._update_staked(_account, idx, _value, INCREMENT)

@external
def on_unstake(_account: address, _value: uint256):
    """
    @notice Triggered by the hook upon unstaking of tokens
    @param _account Originator of the staked tokens
    @param _value Amount of tokens to unstake
    """
    idx: uint256 = self.depositors[msg.sender] - 1
    self._update_staked(_account, idx, _value, DECREMENT)

@external
def claim(_account: address) -> uint256:
    """
    @notice Claim rewards on behalf of an account
    @param _account Account to claim rewards for
    @return Amount of rewards tokens claimed
    """
    assert self.claimers[msg.sender]
    assert self._sync_rewards()
    for i: uint256 in range(3):
        staked: uint256 = self.staked[i][_account].amount
        if staked > 0:
            self._sync_integral(i)
            self._sync_account_integral(i, _account)

    pending: uint256 = self.pending_rewards[_account]
    if pending > 0:
        self.pending_rewards[_account] = 0
        assert extcall token.transfer(msg.sender, pending, default_return_value=True)
        log Claim(account=_account, rewards=pending)

    return pending

@external
def reclaim(_idx: uint256, _account: address) -> (uint256, uint256):
    """
    @notice Reclaim expired rewards
    @param _idx Liquid locker index
    @param _account Account to reclaim rewards for
    @return Tuple with amount of rewards reclaimed and bounty amount received
    """
    assert self._sync_rewards()
    assert self._sync_integral(_idx)

    staked: uint256 = self.staked[_idx][_account].amount
    if staked == 0:
        return 0, 0

    epoch: uint256 = self._epoch() - self.reward_expiration
    integral: uint256 = self.reward_integral_snapshot[_idx][epoch]
    account_integral: uint256 = self.account_reward_integral[_idx][_account]
    if account_integral >= integral:
        return 0, 0

    rewards: uint256 = (integral - account_integral) * staked // PRECISION
    self.account_reward_integral[_idx][_account] = integral
    if rewards == 0:
        return 0, 0

    bounty: uint256 = rewards * self.reclaim_bounty // BOUNTY_PRECISION
    log Reclaim(caller=msg.sender, account=_account, idx=_idx, rewards=rewards, bounty=bounty)

    if bounty > 0:
        rewards -= bounty
        assert extcall token.transfer(msg.sender, bounty, default_return_value=True)

    if rewards > 0:
        assert extcall token.transfer(self.reclaim_recipient, rewards, default_return_value=True)

    return rewards, bounty

@external
def sync_total_rewards() -> bool:
    """
    @notice Synchronize total rewards up until now
    @return True: rewards are fully synced, False: not fully synced
    """
    return self._sync_rewards()

@external
def sync_rewards(_idx: uint256, _account: address = empty(address)) -> bool:
    """
    @notice Synchronize rewards for a specific LL up until now
    @param _idx Liquid locker index
    @param _account Also update rewards for this specific account (optional)
    @return True: rewards are fully synced, False: not fully synced
    """
    assert _idx < 3
    assert self._sync_rewards()

    synced: bool = self._sync_integral(_idx)
    if _account != empty(address):
        self._sync_account_integral(_idx, _account)
    return synced

@external
def set_depositor(_previous: address, _depositor: address):
    """
    @notice Replace a liquid locker depositor
    @param _previous Old depositor address
    @param _depositor New depositor address
    @dev Can only be called by management
    @dev Caller is responsible for ensuring consistency between the old and new depositor
    """
    assert msg.sender == self.management
    number: uint256 = self.depositors[_previous]
    assert number > 0
    assert self.depositors[_depositor] == 0

    self.depositors[_previous] = 0
    self.depositors[_depositor] = number
    log SetDepositor(idx=number - 1, depositor=_depositor)

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
def set_unboosted_weights(_weights: uint256[3]):
    """
    @notice Set unboosted weight of each liquid locker
    @param _weights Unboosted weights
    @dev Can only be called by management
    """
    assert msg.sender == self.management

    epoch: uint256 = 0
    if block.timestamp >= genesis:
        epoch = self._epoch()

    total: uint256 = _weights[0] + _weights[1] + _weights[2]
    self.total_unboosted_weight = total

    for i: uint256 in range(3):
        assert self.current_rewards[i].timestamp // EPOCH_LENGTH == epoch
        if total == 0:
            self.normalized_weights[i] = 0
        else:    
            self.normalized_weights[i] = NORM_WEIGHT_PRECISION * _weights[i] // total
    log SetUnboostedWeights(weights=_weights)

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
def _update_total_staked(_idx: uint256, _amount: uint256, _increment: bool):
    """
    @notice Increase/decrease the total staked amount of a liquid locker
    """
    assert self._sync_rewards()
    assert self._sync_integral(_idx)

    current_epoch: uint256 = self._epoch()
    staked: Staked = self.total_staked[_idx]

    # snapshot
    if current_epoch > staked.epoch:
        self.previous_total_staked[_idx] = staked

    if _increment == INCREMENT:
        staked.amount += _amount
    else:
        staked.amount -= _amount

    staked.epoch = current_epoch
    self.total_staked[_idx] = staked

@internal
def _update_staked(_account: address, _idx: uint256, _amount: uint256, _increment: bool):
    """
    @notice Increase/decrease the staked amount of a liquid locker of a specific account
    """
    self._update_total_staked(_idx, _amount, _increment)
    self._sync_account_integral(_idx, _account)

    current_epoch: uint256 = self._epoch()
    staked: Staked = self.staked[_idx][_account]

    # snapshot
    if current_epoch > staked.epoch:
        self.previous_staked[_idx][_account] = staked

    if _increment == INCREMENT:
        if staked.time > 0:
            staked.time = min(block.timestamp - staked.time, RAMP_LENGTH)
        # amount-weighted average time
        staked.time = block.timestamp - (staked.amount * staked.time) // (staked.amount + _amount)
        staked.amount += _amount
    else:
        staked.amount -= _amount
        if staked.amount == 0:
            staked.time = 0

    staked.epoch = current_epoch
    self.staked[_idx][_account] = staked

@internal
def _sync_rewards() -> bool:
    """
    @notice Synchronize rewards by repeatedly claiming from the distributor
    """
    current_epoch: uint256 = self._epoch()
    reward_epoch: uint256 = self.reward_epoch

    distributor: IDistributor = self.distributor
    for i: uint256 in range(32):
        if reward_epoch == current_epoch:
            break
        reward_epoch += 1
        self.epoch_total_rewards[reward_epoch] = (extcall distributor.claim())[2]

    self.reward_epoch = reward_epoch
    return reward_epoch == current_epoch

@internal
def _sync_integral(_idx: uint256) -> bool:
    """
    @notice Synchronize integral for a specific liquid locker
            Rewards must be synced before calling
    """
    current_epoch: uint256 = self._epoch()
    unlocked: uint256 = 0
    ew: Rewards = self.current_rewards[_idx]
    epoch: uint256 = unsafe_div(ew.timestamp, EPOCH_LENGTH)
    synced: bool = epoch == current_epoch
    last_streamed: uint256 = (ew.timestamp % EPOCH_LENGTH) * ew.rewards // EPOCH_LENGTH
    ew.timestamp = block.timestamp - genesis
    integral: uint256 = self.reward_integral[_idx]
    total_staked: uint256 = self.total_staked[_idx].amount
    
    if not synced:
        # rollover to new epoch. first finalize the last one
        unlocked = ew.rewards - last_streamed
        last_streamed = 0

        # save integral snapshot
        self.reward_integral_snapshot[_idx][epoch] = integral + unlocked * PRECISION // total_staked

        # fast forward through any other completed epochs
        weight: uint256 = self.normalized_weights[_idx]

        if weight == 0:
            # liquid locker is disabled, skip ahead
            ew.rewards = 0
        else:
            epoch_rewards: uint256 = 0
            for i: uint256 in range(32):
                epoch += 1
                epoch_rewards = self.epoch_total_rewards[epoch] * weight // NORM_WEIGHT_PRECISION
                synced = epoch == current_epoch
                if synced:
                    break
                else:
                    unlocked += epoch_rewards
                    self.reward_integral_snapshot[_idx][epoch] = integral + unlocked * PRECISION // total_staked

            if synced:
                # fully caught up
                ew.rewards = epoch_rewards
            else:
                # not fully caught up. we already added the epoch's full amount to `unlocked`, so we 
                # zero out the epoch rewards to not double count it in the next call
                ew.timestamp = epoch * EPOCH_LENGTH
                ew.rewards = 0

    self.current_rewards[_idx] = ew

    # accrue rewards from this epoch
    streamed: uint256 = (ew.timestamp % EPOCH_LENGTH) * ew.rewards // EPOCH_LENGTH
    unlocked += streamed - last_streamed
    if unlocked == 0:
        return synced

    # update integral
    self.reward_integral[_idx] = integral + unlocked * PRECISION // total_staked

    return synced

@internal
def _sync_account_integral(_idx: uint256, _account: address):
    """
    @notice Synchronize integral for a specific liquid locker and account
            Global integral must be synced before calling
    """
    staked: uint256 = self.staked[_idx][_account].amount
    integral: uint256 = self.reward_integral[_idx]
    pending: uint256 = self.pending_rewards[_account]
    if staked > 0:
        pending += (integral - self.account_reward_integral[_idx][_account]) * staked // PRECISION
        self.pending_rewards[_account] = pending
    self.account_reward_integral[_idx][_account] = integral
