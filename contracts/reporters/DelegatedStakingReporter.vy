# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Delegated Staking Reporter (stYFI+)
@notice Stateless reporter for the delegated vault. Stores balance in distributor user_data
        and reports weight = balance.
"""

interface IHooks:
    def on_transfer(_caller: address, _from: address, _to: address, _value: uint256): nonpayable
    def on_stake(_caller: address, _account: address, _value: uint256): nonpayable
    def on_unstake(_account: address, _value: uint256): nonpayable
    def instant_withdrawal(_account: address) -> bool: view

interface IRewardDistributorV2:
    def report_account_state(_component_id: uint256, _account: address, _user_data: uint256): nonpayable
    def get_account_state(_component_id: uint256, _account: address) -> (uint256, uint256): view

implements: IHooks

# Immutables
distributor: public(immutable(IRewardDistributorV2))
component_id: public(immutable(uint256))
depositor: public(immutable(address))


@deploy
def __init__(_distributor: address, _component_id: uint256, _depositor: address):
    distributor = IRewardDistributorV2(_distributor)
    component_id = _component_id
    depositor = _depositor


# ═══════════════════════════════════════════════════════════════════════════════
# HOOKS
# ═══════════════════════════════════════════════════════════════════════════════

@external
def on_stake(_caller: address, _account: address, _amount: uint256):
    assert msg.sender == depositor, "unauthorized"
    self._update_balance(_account, convert(_amount, int256))


@external
def on_unstake(_account: address, _amount: uint256):
    assert msg.sender == depositor, "unauthorized"
    self._update_balance(_account, -convert(_amount, int256))


@external
def on_transfer(_caller: address, _from: address, _to: address, _amount: uint256):
    assert msg.sender == depositor, "unauthorized"
    self._update_balance(_from, -convert(_amount, int256))
    self._update_balance(_to, convert(_amount, int256))


@external
@view
def instant_withdrawal(_account: address) -> bool:
    return False

# Distributor callback to compute weight from user_data
@external
@view
def compute_weight(_account: address, _user_data: uint256, _epoch: uint256) -> uint256:
    return _user_data


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNALS
# ═══════════════════════════════════════════════════════════════════════════════

@internal
def _update_balance(_account: address, _delta: int256):
    old_weight: uint256 = 0
    old_data: uint256 = 0
    old_weight, old_data = staticcall distributor.get_account_state(component_id, _account)

    balance: uint256 = old_data
    if _delta > 0:
        balance += convert(_delta, uint256)
    else:
        balance -= convert(-_delta, uint256)

    extcall distributor.report_account_state(component_id, _account, balance)
