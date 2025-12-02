# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Delegated Staking Reward Distributor
@author Yearn Finance
@license GNU AGPLv3
@notice Tracks staking balances through the hook. Rewards are claimed from the StakingRewardDistributor 
        directly before a state change. They are passed through to the user in proportion to their share
        of deposits.
"""

from ethereum.ercs import IERC20

interface IHooks:
    def on_transfer(_caller: address, _from: address, _to: address, _value: uint256): nonpayable
    def on_stake(_caller: address, _account: address, _value: uint256): nonpayable
    def on_unstake(_account: address, _value: uint256): nonpayable

interface IDistributor:
    def claim(_account: address) -> uint256: nonpayable

implements: IHooks

genesis: public(immutable(uint256))
token: public(immutable(IERC20))
management: public(address)
pending_management: public(address)

depositor: public(address)
distributor: public(IDistributor)
distributor_claim: public(address)
claimers: public(HashMap[address, bool])

total_weight: public(uint256)
weights: public(HashMap[address, uint256])

reward_integral: public(uint256)
account_reward_integral: public(HashMap[address, uint256])
pending_rewards: public(HashMap[address, uint256])

event Claim:
    account: indexed(address)
    rewards: uint256

event SetDepositor:
    depositor: address

event SetDistributor:
    distributor: address

event SetDistributorClaim:
    claim: address

event SetClaimer:
    account: address
    claimer: bool

event PendingManagement:
    management: indexed(address)

event SetManagement:
    management: indexed(address)

EPOCH_LENGTH: constant(uint256) = 14 * 24 * 60 * 60
PRECISION: constant(uint256) = 10**30

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

@external
def on_transfer(_caller: address, _from: address, _to: address, _amount: uint256):
    """
    @notice Triggered by the hook upon transfer of tokens
    @param _caller Originator of the transfer
    @param _from Sender of the token
    @param _to Recipient of the tokens
    @param _amount Amount of tokens to transfer
    """
    assert msg.sender == self.depositor
    self._sync_integral()
    self._sync_account_integral(_from)
    self._sync_account_integral(_to)

    self.weights[_from] -= _amount
    self.weights[_to] += _amount

@external
def on_stake(_caller: address, _account: address, _amount: uint256):
    """
    @notice Triggered by the hook upon staking of tokens
    @param _caller Originator of the tokens
    @param _account Recipient of the staked tokens
    @param _amount Amount of tokens to stake
    """
    assert msg.sender == self.depositor
    self._sync_integral()
    self._sync_account_integral(_account)

    self.total_weight += _amount
    self.weights[_account] += _amount

@external
def on_unstake(_account: address, _amount: uint256):
    """
    @notice Triggered by the hook upon unstaking of tokens
    @param _account Originator of the staked tokens
    @param _amount Amount of tokens to unstake
    """
    assert msg.sender == self.depositor
    self._sync_integral()
    self._sync_account_integral(_account)

    self.total_weight -= _amount
    self.weights[_account] -= _amount

@external
def claim(_account: address) -> uint256:
    """
    @notice Claim rewards on behalf of an account
    @param _account Account to claim rewards for
    @return Amount of rewards tokens claimed
    """
    if self.weights[_account] == 0 and self.pending_rewards[_account] == 0:
        # shortcut accounts that are guaranteed to have no rewards
        return 0

    assert self.claimers[msg.sender]
    self._sync_integral()
    pending: uint256 = self._sync_account_integral(_account)

    if pending > 0:
        self.pending_rewards[_account] = 0
        assert extcall token.transfer(msg.sender, pending, default_return_value=True)
        log Claim(account=_account, rewards=pending)

    return pending

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
def set_distributor(_distributor: address):
    """
    @notice Set upstream staking reward distributor
    @param _distributor Distributor address
    @dev Can only be called by management
    """
    assert msg.sender == self.management

    self.distributor = IDistributor(_distributor)
    log SetDistributor(distributor=_distributor)

@external
def set_distributor_claim(_claim: address):
    """
    @notice Set address to claim rewards for. Should normally be set to the depositor,
            unless middleware has been injected
    @param _claim The address to claim rewards on behalf of
    @dev Can only be called by management
    """
    assert msg.sender == self.management

    self.distributor_claim = _claim
    log SetDistributorClaim(claim=_claim)

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
def _sync_integral():
    """
    @notice Claim rewards and update integral
    """
    total_weight: uint256 = self.total_weight
    if total_weight < 10**12:
        # rewards only accrue when there are depositors
        return

    rewards: uint256 = extcall self.distributor.claim(self.distributor_claim)
    if rewards > 0:
        self.reward_integral += rewards * PRECISION // total_weight

@internal
def _sync_account_integral(_account: address) -> uint256:
    """
    @notice Sync integral for a specific account
            Global integral should be synced prior to calling this
    """
    weight: uint256 = self.weights[_account]
    integral: uint256 = self.reward_integral
    pending: uint256 = self.pending_rewards[_account]
    if weight > 0:
        pending += (integral - self.account_reward_integral[_account]) * weight // PRECISION
        self.pending_rewards[_account] = pending
    self.account_reward_integral[_account] = integral
    return pending
