# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Config Hub
@author Yearn Finance
@license GNU AGPLv3
@notice Central configuration oracle for the stYFI protocol.
        Manages management, blacklist, epoch parameters, and component configuration.
        This is a PURE CONFIG contract - NO balances, NO weights, NO reward state.
        All balance/weight tracking is handled by RewardDistributorV2.
"""

from ethereum.ercs import IERC20

struct Scale:
    numerator: uint256
    denominator: uint256

struct ComponentConfig:
    enabled: bool
    weight_scale: Scale        # (0,0) = use global
    param1: uint256            # generic param slot
    param2: uint256            # generic param slot

# Constants
EPOCH_LENGTH: constant(uint256) = 14 * 24 * 60 * 60
MAX_NUM_COMPONENTS: constant(uint256) = 32
BOUNTY_PRECISION: constant(uint256) = 10_000

# Immutables
genesis: public(immutable(uint256))
reward_token: public(immutable(IERC20))

# Management (two-step transfer)
management: public(address)
pending_management: public(address)

# Blacklist
blacklist: public(HashMap[address, bool])

# Global Parameters
weight_scale_global: public(Scale)
reclaim_bounty: public(uint256)
reclaim_recipient: public(address)
report_bounty: public(uint256)
report_recipient: public(address)
reclaim_expiration_epochs: public(uint256)

# Component Configuration (NO weights, NO balances - just config)
num_components: public(uint256)
component_config: public(HashMap[uint256, ComponentConfig])

# Events
event PendingManagement:
    management: indexed(address)

event SetManagement:
    management: indexed(address)

event SetBlacklist:
    account: indexed(address)
    blacklisted: bool

event SetWeightScaleGlobal:
    numerator: uint256
    denominator: uint256

event SetReclaimParams:
    expiration_epochs: uint256
    bounty: uint256
    recipient: address

event SetReportParams:
    bounty: uint256
    recipient: address

event AddComponent:
    component_id: indexed(uint256)
    param1: uint256
    param2: uint256

event UpdateComponentEnabled:
    component_id: indexed(uint256)
    enabled: bool

event SetComponentWeightScale:
    component_id: indexed(uint256)
    numerator: uint256
    denominator: uint256

event SetComponentParams:
    component_id: indexed(uint256)
    param1: uint256
    param2: uint256


@deploy
def __init__(_genesis: uint256, _reward_token: address):
    """
    @notice Constructor
    @param _genesis Genesis timestamp (should be epoch-aligned)
    @param _reward_token Address of the reward token
    """
    assert _genesis % EPOCH_LENGTH == 0  # Must be epoch-aligned

    genesis = _genesis
    reward_token = IERC20(_reward_token)

    self.management = msg.sender

    # Set sensible defaults
    self.weight_scale_global = Scale(numerator=4, denominator=1)
    self.reclaim_expiration_epochs = 26
    self.reclaim_recipient = msg.sender
    self.report_recipient = msg.sender


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW FUNCTIONS - EPOCH HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

@external
@view
def epoch() -> uint256:
    """
    @notice Query the current epoch number
    @return The current epoch number
    """
    return self._epoch()


@external
@view
def epoch_start_time(_epoch: uint256) -> uint256:
    """
    @notice Get the start timestamp of a specific epoch
    @param _epoch Epoch number
    @return Unix timestamp of epoch start
    """
    return genesis + _epoch * EPOCH_LENGTH


@external
@view
def epoch_end_time(_epoch: uint256) -> uint256:
    """
    @notice Get the end timestamp of a specific epoch
    @param _epoch Epoch number
    @return Unix timestamp of epoch end
    """
    return genesis + (_epoch + 1) * EPOCH_LENGTH


@internal
@view
def _epoch() -> uint256:
    return unsafe_div(block.timestamp - genesis, EPOCH_LENGTH)


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW FUNCTIONS - AUTHORIZATION
# ═══════════════════════════════════════════════════════════════════════════════

@external
@view
def is_allowed(_addr: address) -> bool:
    """
    @notice Check if an address is allowed to perform privileged operations
    @param _addr Address to check
    @return True if address is management AND not blacklisted
    @dev This is the primary authorization check for all other modules
    """
    return _addr == self.management and not self.blacklist[_addr]


@external
@view
def is_blacklisted(_addr: address) -> bool:
    """
    @notice Check if an address is blacklisted
    @param _addr Address to check
    @return True if address is blacklisted
    """
    return self.blacklist[_addr]


# ═══════════════════════════════════════════════════════════════════════════════
# VIEW FUNCTIONS - PARAMETER GETTERS
# ═══════════════════════════════════════════════════════════════════════════════

@external
@view
def get_weight_scale(_component_id: uint256) -> Scale:
    """
    @notice Get the effective weight scale for a component
    @param _component_id Component ID
    @return Scale struct (uses component override if set, otherwise global)
    """
    config: ComponentConfig = self.component_config[_component_id]
    if config.weight_scale.denominator > 0:
        return config.weight_scale
    return self.weight_scale_global


@external
@view
def get_component_config(_component_id: uint256) -> ComponentConfig:
    """
    @notice Get component configuration
    @param _component_id Component ID
    @return ComponentConfig struct
    """
    return self.component_config[_component_id]


@external
@view
def get_component_params(_component_id: uint256) -> (uint256, uint256):
    """
    @notice Get generic params for a component
    @param _component_id Component ID
    @return Tuple (param1, param2)
    """
    config: ComponentConfig = self.component_config[_component_id]
    return config.param1, config.param2


@external
@view
def is_component_enabled(_component_id: uint256) -> bool:
    """
    @notice Check if a component is enabled
    @param _component_id Component ID
    @return True if component is enabled
    """
    return self.component_config[_component_id].enabled


@external
@view
def get_reclaim_params() -> (uint256, uint256, address):
    """
    @notice Get reclaim parameters
    @return Tuple of (expiration_epochs, bounty_bps, recipient)
    """
    return self.reclaim_expiration_epochs, self.reclaim_bounty, self.reclaim_recipient


@external
@view
def get_report_params() -> (uint256, address):
    """
    @notice Get report parameters
    @return Tuple of (bounty_bps, recipient)
    """
    return self.report_bounty, self.report_recipient


# ═══════════════════════════════════════════════════════════════════════════════
# MANAGEMENT FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@external
def set_management(_management: address):
    """
    @notice Set the pending management address
    @param _management New pending management address
    """
    assert msg.sender == self.management

    self.pending_management = _management
    log PendingManagement(management=_management)


@external
def accept_management():
    """
    @notice Accept management role
    """
    assert msg.sender == self.pending_management

    self.pending_management = empty(address)
    self.management = msg.sender
    log SetManagement(management=msg.sender)


@external
def set_blacklist(_account: address, _blacklisted: bool):
    """
    @notice Add or remove an address from the blacklist
    @param _account Address to modify
    @param _blacklisted True to blacklist, False to remove
    """
    assert msg.sender == self.management

    self.blacklist[_account] = _blacklisted
    log SetBlacklist(account=_account, blacklisted=_blacklisted)


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL PARAMETER SETTERS
# ═══════════════════════════════════════════════════════════════════════════════

@external
def set_weight_scale_global(_numerator: uint256, _denominator: uint256):
    """
    @notice Set the global weight scale
    @param _numerator Scale numerator
    @param _denominator Scale denominator
    """
    assert msg.sender == self.management
    assert _numerator > 0 and _denominator > 0

    self.weight_scale_global = Scale(numerator=_numerator, denominator=_denominator)
    log SetWeightScaleGlobal(numerator=_numerator, denominator=_denominator)


@external
def set_reclaim_params(_expiration_epochs: uint256, _bounty: uint256, _recipient: address):
    """
    @notice Set reclaim parameters
    @param _expiration_epochs Number of epochs after which rewards can be reclaimed
    @param _bounty Bounty in basis points for the caller
    @param _recipient Recipient of reclaimed rewards
    """
    assert msg.sender == self.management
    assert _expiration_epochs > 1
    assert _bounty <= BOUNTY_PRECISION
    assert _recipient != empty(address) or _bounty == BOUNTY_PRECISION

    self.reclaim_expiration_epochs = _expiration_epochs
    self.reclaim_bounty = _bounty
    self.reclaim_recipient = _recipient
    log SetReclaimParams(expiration_epochs=_expiration_epochs, bounty=_bounty, recipient=_recipient)


@external
def set_report_params(_bounty: uint256, _recipient: address):
    """
    @notice Set report parameters (for early exit reporting)
    @param _bounty Bounty in basis points for the caller
    @param _recipient Recipient of reported rewards
    """
    assert msg.sender == self.management
    assert _bounty <= BOUNTY_PRECISION
    assert _recipient != empty(address) or _bounty == BOUNTY_PRECISION

    self.report_bounty = _bounty
    self.report_recipient = _recipient
    log SetReportParams(bounty=_bounty, recipient=_recipient)


# ═══════════════════════════════════════════════════════════════════════════════
# COMPONENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@external
def add_component(_param1: uint256 = 0, _param2: uint256 = 0) -> uint256:
    """
    @notice Register a new component
    @param _param1 Generic parameter (optional)
    @param _param2 Generic parameter (optional)
    @return The assigned component ID
    """
    assert msg.sender == self.management

    num: uint256 = self.num_components
    assert num < MAX_NUM_COMPONENTS

    self.component_config[num] = ComponentConfig(
        enabled=True,
        weight_scale=Scale(numerator=0, denominator=0),  # Use global by default
        param1=_param1,
        param2=_param2
    )
    self.num_components = num + 1

    log AddComponent(component_id=num, param1=_param1, param2=_param2)
    return num


@external
def set_component_enabled(_component_id: uint256, _enabled: bool):
    """
    @notice Enable or disable a component
    @param _component_id Component ID
    @param _enabled True to enable, False to disable
    """
    assert msg.sender == self.management
    assert _component_id < self.num_components

    self.component_config[_component_id].enabled = _enabled
    log UpdateComponentEnabled(component_id=_component_id, enabled=_enabled)


@external
def set_component_weight_scale(_component_id: uint256, _numerator: uint256, _denominator: uint256):
    """
    @notice Set component-specific weight scale override
    @param _component_id Component ID
    @param _numerator Scale numerator (0 to use global)
    @param _denominator Scale denominator (0 to use global)
    """
    assert msg.sender == self.management
    assert _component_id < self.num_components
    assert (_numerator == 0 and _denominator == 0) or (_numerator > 0 and _denominator > 0)

    self.component_config[_component_id].weight_scale = Scale(
        numerator=_numerator,
        denominator=_denominator
    )
    log SetComponentWeightScale(component_id=_component_id, numerator=_numerator, denominator=_denominator)


@external
def set_component_params(_component_id: uint256, _param1: uint256, _param2: uint256):
    """
    @notice Set generic component parameters
    @param _component_id Component ID
    @param _param1 Generic parameter
    @param _param2 Generic parameter
    """
    assert msg.sender == self.management
    assert _component_id < self.num_components

    self.component_config[_component_id].param1 = _param1
    self.component_config[_component_id].param2 = _param2
    log SetComponentParams(component_id=_component_id, param1=_param1, param2=_param2)
