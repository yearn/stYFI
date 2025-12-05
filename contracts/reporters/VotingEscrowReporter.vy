# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Voting Escrow Reporter (generic)
@notice Maintains ve snapshots and reports computed lock weights to the distributor.
        All lock state is stored in the distributor via user_data.
"""

interface IConfigHub:
    def epoch() -> uint256: view
    def is_allowed(_account: address) -> bool: view

interface IRewardDistributorV2:
    def report_account_state(_component_id: uint256, _account: address, _user_data: uint256): nonpayable
    def get_account_state(_component_id: uint256, _account: address) -> (uint256, uint256): view

# Constants
MAX_LOCK_EPOCHS: constant(uint256) = 104

# Packing user_data: amount (128) | boost_epochs (64) | unlock_epoch (64)
AMOUNT_SHIFT: constant(uint256) = 128
BOOST_SHIFT: constant(uint256) = 64
BOOST_MASK: constant(uint256) = (1 << 64) - 1
UNLOCK_MASK: constant(uint256) = (1 << 64) - 1

# Immutables
config_hub: public(immutable(IConfigHub))
distributor: public(immutable(IRewardDistributorV2))
component_id: public(immutable(uint256))

# Snapshot storage
snapshot_amount: public(HashMap[address, uint256])
snapshot_unlock_epoch: public(HashMap[address, uint256])

# Events
event Migrate:
    account: indexed(address)
    amount: uint256
    unlock_epoch: uint256

event ReportEarlyExit:
    caller: indexed(address)
    account: indexed(address)
    rewards: uint256
    bounty: uint256

event SetSnapshot:
    account: indexed(address)
    amount: uint256
    unlock_epoch: uint256


@deploy
def __init__(_config_hub: address, _distributor: address, _component_id: uint256):
    config_hub = IConfigHub(_config_hub)
    distributor = IRewardDistributorV2(_distributor)
    component_id = _component_id


# ═══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT MANAGEMENT (ConfigHub-gated)
# ═══════════════════════════════════════════════════════════════════════════════

@external
def set_snapshot(_account: address, _amount: uint256, _unlock_epoch: uint256):
    assert staticcall config_hub.is_allowed(msg.sender), "unauthorized"
    self.snapshot_amount[_account] = _amount
    self.snapshot_unlock_epoch[_account] = _unlock_epoch
    log SetSnapshot(account=_account, amount=_amount, unlock_epoch=_unlock_epoch)


# ═══════════════════════════════════════════════════════════════════════════════
# MIGRATION
# ═══════════════════════════════════════════════════════════════════════════════

@external
def migrate():
    account: address = msg.sender
    current_epoch: uint256 = staticcall config_hub.epoch()

    amount: uint256 = self.snapshot_amount[account]
    unlock_epoch: uint256 = self.snapshot_unlock_epoch[account]
    assert amount > 0, "no lock"
    assert unlock_epoch > current_epoch, "lock expired"

    boost_epochs: uint256 = unlock_epoch - current_epoch
    if boost_epochs > MAX_LOCK_EPOCHS:
        boost_epochs = MAX_LOCK_EPOCHS

    user_data: uint256 = (amount << AMOUNT_SHIFT) | (boost_epochs << BOOST_SHIFT) | unlock_epoch
    extcall distributor.report_account_state(component_id, account, user_data)

    log Migrate(account=account, amount=amount, unlock_epoch=unlock_epoch)


# ═══════════════════════════════════════════════════════════════════════════════
# EARLY EXIT REPORTING
# ═══════════════════════════════════════════════════════════════════════════════

@external
def report_early_exit(_account: address):
    """
    @notice Report early exit by zeroing weight/user_data in distributor.
    """
    self.snapshot_amount[_account] = 0
    self.snapshot_unlock_epoch[_account] = 0
    extcall distributor.report_account_state(component_id, _account, 0)
    log ReportEarlyExit(caller=msg.sender, account=_account, rewards=0, bounty=0)


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW CALLBACK FOR DISTRIBUTOR
# ═══════════════════════════════════════════════════════════════════════════════

@external
@view
def compute_weight(_account: address, _user_data: uint256, _epoch: uint256) -> uint256:
    amount: uint256 = _user_data >> AMOUNT_SHIFT
    boost_epochs: uint256 = (_user_data >> BOOST_SHIFT) & BOOST_MASK
    unlock_epoch: uint256 = _user_data & UNLOCK_MASK

    if amount == 0 or _epoch >= unlock_epoch:
        return 0

    remaining_boost: uint256 = 0
    if boost_epochs > _epoch:
        remaining_boost = boost_epochs - _epoch
        remaining_time: uint256 = unlock_epoch - _epoch
        if remaining_boost > remaining_time:
            remaining_boost = remaining_time

    slope: uint256 = amount // MAX_LOCK_EPOCHS
    return amount + slope * remaining_boost
