# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Staking Reporter (Generic)
@notice Stateless reporter for the stYFI vault. Computes ramped weight from stored
        timestamp/balance (kept in the distributor) and reports the updated weight.
"""

interface IHooks:
    def on_transfer(_caller: address, _from: address, _to: address, _value: uint256): nonpayable
    def on_stake(_caller: address, _account: address, _value: uint256): nonpayable
    def on_unstake(_account: address, _value: uint256): nonpayable
    def instant_withdrawal(_account: address) -> bool: view

interface IConfigHub:
    def epoch() -> uint256: view

interface IRewardDistributorV2:
    def report_account_state(_component_id: uint256, _account: address, _user_data: uint256): nonpayable
    def get_account_state(_component_id: uint256, _account: address) -> (uint256, uint256): view

implements: IHooks

# Constants
RAMP_LENGTH: constant(uint256) = 4 * 14 * 24 * 60 * 60  # 4 epochs

# Packing: | timestamp (128 bits) | balance (128 bits) |
TS_SHIFT: constant(uint256) = 128
TS_MASK: constant(uint256) = 2**128 - 1
BAL_MASK: constant(uint256) = 2**128 - 1

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
    self._update_account(_account, convert(_amount, int256))


@external
def on_unstake(_account: address, _amount: uint256):
    assert msg.sender == depositor, "unauthorized"
    self._update_account(_account, -convert(_amount, int256))


@external
def on_transfer(_caller: address, _from: address, _to: address, _amount: uint256):
    assert msg.sender == depositor, "unauthorized"
    self._update_account(_from, -convert(_amount, int256))
    self._update_account(_to, convert(_amount, int256))


@external
@view
def instant_withdrawal(_account: address) -> bool:
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNALS
# ═══════════════════════════════════════════════════════════════════════════════

@internal
def _update_account(_account: address, _delta: int256):
    now_ts: uint256 = block.timestamp
    old_weight: uint256 = 0
    old_data: uint256 = 0
    old_weight, old_data = staticcall distributor.get_account_state(component_id, _account)

    timestamp: uint256 = old_data >> TS_SHIFT
    balance: uint256 = old_data & BAL_MASK

    # Apply delta
    if _delta > 0:
        balance += convert(_delta, uint256)
        # Weighted average timestamp for ramp
        if timestamp == 0:
            timestamp = now_ts
        else:
            elapsed: uint256 = now_ts - timestamp
            if elapsed > RAMP_LENGTH:
                elapsed = RAMP_LENGTH
            timestamp = now_ts - (balance - convert(_delta, uint256)) * elapsed // balance
    else:
        amt: uint256 = convert(-_delta, uint256)
        balance -= amt
        if balance == 0:
            timestamp = 0

    # Compute ramped weight
    weight: uint256 = 0
    if balance > 0:
        elapsed2: uint256 = now_ts - timestamp
        if elapsed2 > RAMP_LENGTH:
            elapsed2 = RAMP_LENGTH
        weight = balance * elapsed2 // RAMP_LENGTH

    new_data: uint256 = (timestamp << TS_SHIFT) | balance
    extcall distributor.report_account_state(component_id, _account, new_data)


@external
@view
def compute_weight(_account: address, _user_data: uint256, _epoch: uint256) -> uint256:
    """
    @notice Called by distributor to compute weight from user_data
    """
    timestamp: uint256 = _user_data >> TS_SHIFT
    balance: uint256 = _user_data & BAL_MASK
    if balance == 0 or timestamp == 0:
        return 0
    elapsed: uint256 = block.timestamp - timestamp
    if elapsed > RAMP_LENGTH:
        elapsed = RAMP_LENGTH
    return balance * elapsed // RAMP_LENGTH
