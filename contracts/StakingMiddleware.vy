# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Staking Middleware
@author Yearn Finance
@license GNU AGPLv3
@notice Middleware contract for StakedYFI hooks. Maintains a list of addresses that have instant
        withdrawals enabled, as well as a blacklist for transfers only. It forwards all state
        modifying calls to a downstream address.
"""

interface IHooks:
    def on_transfer(_caller: address, _from: address, _to: address, _value: uint256): nonpayable
    def on_stake(_caller: address, _account: address, _value: uint256): nonpayable
    def on_unstake(_account: address, _value: uint256): nonpayable
    def instant_withdrawal(_account: address) -> bool: view

implements: IHooks

upstream: public(immutable(address))
downstream: public(immutable(IHooks))
management: public(address)
pending_management: public(address)

instant_withdrawal: public(HashMap[address, bool])
blacklist: public(HashMap[address, bool])

event SetInstantWithdrawal:
    account: address
    instant: bool

event SetBlacklist:
    account: indexed(address)
    blacklist: bool

event PendingManagement:
    management: indexed(address)

event SetManagement:
    management: indexed(address)

@deploy
def __init__(_upstream: address, _downstream: address):
    """
    @notice Constructor
    @param _upstream The address where hook calls originate from
    @param _downstream The address where hook calls are forwarded to
    """
    upstream = _upstream
    downstream = IHooks(_downstream)
    self.management = msg.sender

@external
def on_transfer(_caller: address, _from: address, _to: address, _value: uint256):
    """
    @notice Triggered by the hook upon transfer of tokens
    @param _caller Originator of the transfer
    @param _from Sender of the token
    @param _to Recipient of the tokens
    @param _value Amount of tokens to transfer
    """
    assert msg.sender == upstream
    assert not self.blacklist[_from]

    extcall downstream.on_transfer(_caller, _from, _to, _value)

@external
def on_stake(_caller: address, _account: address, _value: uint256):
    """
    @notice Triggered by the hook upon staking of tokens
    @param _caller Originator of the tokens
    @param _account Recipient of the staked tokens
    @param _value Amount of tokens to stake
    """
    assert msg.sender == upstream

    extcall downstream.on_stake(_caller, _account, _value)

@external
def on_unstake(_account: address, _value: uint256):
    """
    @notice Triggered by the hook upon unstaking of tokens
    @param _account Originator of the staked tokens
    @param _value Amount of tokens to unstake
    """
    assert msg.sender == upstream

    extcall downstream.on_unstake(_account, _value)

@external
def set_instant_withdrawal(_account: address, _instant: bool):
    """
    @notice Set the instant withdrawal status for a specific account
    @param _account Account to set instant withdrawal status for
    @param _instant True: allow instant withdrawals, False: disallow instant withdrawals
    @dev Can only be called by management
    """
    assert msg.sender == self.management

    self.instant_withdrawal[_account] = _instant
    log SetInstantWithdrawal(account=_account, instant=_instant)

@external
def set_blacklist(_account: address, _blacklist: bool):
    """
    @notice Set the transfer blacklist status for a specific account
    @param _account Account to set transfer blacklist status for
    @param _blacklist True: add to blacklist, False: remove from blacklist
    @dev Can only be called by management
    """
    assert msg.sender == self.management

    self.blacklist[_account] = _blacklist
    log SetBlacklist(account=_account, blacklist=_blacklist)

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
