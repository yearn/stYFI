# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Liquid Locker Reporter (generic, 3 lockers)
@notice Stateless reporter that packs per-locker balances in distributor user_data and
        reports boosted/normalized weight.
"""

interface ILLHooks:
    def on_stake(_caller: address, _account: address, _value: uint256): nonpayable
    def on_unstake(_account: address, _value: uint256): nonpayable

interface IRewardDistributorV2:
    def report_account_state(_component_id: uint256, _account: address, _user_data: uint256): nonpayable
    def get_account_state(_component_id: uint256, _account: address) -> (uint256, uint256): view

interface IConfigHub:
    def is_allowed(_account: address) -> bool: view
    def epoch() -> uint256: view

implements: ILLHooks

# Constants
MAX_LLS: constant(uint256) = 3
BOOST_DURATION: constant(uint256) = 104  # epochs
# Normalized weights sum to 1e30
NORM: constant(uint256[MAX_LLS]) = [
    333_333_333_333_333_333_333_333_333_333,
    333_333_333_333_333_333_333_333_333_333,
    333_333_333_333_333_333_333_333_333_334
]
PRECISION: constant(uint256) = 10**30

# Packing balances: 80 bits each (fits comfortably)
SHIFT1: constant(uint256) = 80
SHIFT2: constant(uint256) = 160
MASK: constant(uint256) = 2**80 - 1

# Immutables
config_hub: public(immutable(IConfigHub))
distributor: public(immutable(IRewardDistributorV2))
component_id: public(immutable(uint256))

# Depositors registry: address => ll_index+1
depositors: public(HashMap[address, uint256])
depositor_addresses: public(address[MAX_LLS])

# Events
event SetDepositor:
    ll_index: indexed(uint256)
    depositor: address


@deploy
def __init__(_config_hub: address, _distributor: address, _component_id: uint256):
    config_hub = IConfigHub(_config_hub)
    distributor = IRewardDistributorV2(_distributor)
    component_id = _component_id


# ═══════════════════════════════════════════════════════════════════════════════
# HOOKS
# ═══════════════════════════════════════════════════════════════════════════════

@external
def on_stake(_caller: address, _account: address, _amount: uint256):
    idx: uint256 = self._ll_index(msg.sender)
    self._update_account(_account, idx, convert(_amount, int256))


@external
def on_unstake(_account: address, _amount: uint256):
    idx: uint256 = self._ll_index(msg.sender)
    self._update_account(_account, idx, -convert(_amount, int256))


# ═══════════════════════════════════════════════════════════════════════════════
# MANAGEMENT (config hub gated via router)
# ═══════════════════════════════════════════════════════════════════════════════

@external
def set_depositor(_ll_index: uint256, _depositor: address):
    assert _ll_index < MAX_LLS, "invalid index"
    assert staticcall config_hub.is_allowed(msg.sender), "unauthorized"
    old: address = self.depositor_addresses[_ll_index]
    if old != empty(address):
        self.depositors[old] = 0

    if _depositor != empty(address):
        assert self.depositors[_depositor] == 0, "already set"
        self.depositors[_depositor] = _ll_index + 1

    self.depositor_addresses[_ll_index] = _depositor
    log SetDepositor(ll_index=_ll_index, depositor=_depositor)


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNALS
# ═══════════════════════════════════════════════════════════════════════════════

@internal
def _ll_index(_depositor: address) -> uint256:
    idx_plus: uint256 = self.depositors[_depositor]
    assert idx_plus > 0, "unauthorized"
    return idx_plus - 1


@internal
def _update_account(_account: address, _ll_index: uint256, _delta: int256):
    old_weight: uint256 = 0
    data: uint256 = 0
    old_weight, data = staticcall distributor.get_account_state(component_id, _account)

    b0: uint256 = data & MASK
    b1: uint256 = (data >> SHIFT1) & MASK
    b2: uint256 = (data >> SHIFT2) & MASK

    if _ll_index == 0:
        if _delta > 0:
            b0 += convert(_delta, uint256)
        else:
            b0 -= convert(-_delta, uint256)
    elif _ll_index == 1:
        if _delta > 0:
            b1 += convert(_delta, uint256)
        else:
            b1 -= convert(-_delta, uint256)
    else:
        if _delta > 0:
            b2 += convert(_delta, uint256)
        else:
            b2 -= convert(-_delta, uint256)

    # Compute boosted weight
    current_epoch: uint256 = staticcall config_hub.epoch()
    weight: uint256 = 0
    base0: uint256 = b0 * NORM[0] // PRECISION
    base1: uint256 = b1 * NORM[1] // PRECISION
    base2: uint256 = b2 * NORM[2] // PRECISION

    if current_epoch < BOOST_DURATION:
        remaining: uint256 = BOOST_DURATION - current_epoch
        boost_num: uint256 = PRECISION + (PRECISION * remaining // BOOST_DURATION)  # up to 2x
        weight = base0 * boost_num // PRECISION
        weight += base1 * boost_num // PRECISION
        weight += base2 * boost_num // PRECISION
    else:
        weight = base0 + base1 + base2

    new_data: uint256 = b0 | (b1 << SHIFT1) | (b2 << SHIFT2)
    extcall distributor.report_account_state(component_id, _account, new_data)


# Distributor callback to compute weight from user_data
@external
@view
def compute_weight(_account: address, _user_data: uint256, _epoch: uint256) -> uint256:
    b0: uint256 = _user_data & MASK
    b1: uint256 = (_user_data >> SHIFT1) & MASK
    b2: uint256 = (_user_data >> SHIFT2) & MASK

    current_epoch: uint256 = staticcall config_hub.epoch()
    base0: uint256 = b0 * NORM[0] // PRECISION
    base1: uint256 = b1 * NORM[1] // PRECISION
    base2: uint256 = b2 * NORM[2] // PRECISION

    if current_epoch < BOOST_DURATION:
        remaining: uint256 = BOOST_DURATION - current_epoch
        boost_num: uint256 = PRECISION + (PRECISION * remaining // BOOST_DURATION)
        return (base0 * boost_num // PRECISION) + (base1 * boost_num // PRECISION) + (base2 * boost_num // PRECISION)

    return base0 + base1 + base2
