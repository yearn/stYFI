# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Weight aggregator
@author Yearn Finance
@license GNU AGPLv3
@notice Aggregates user balances inside staking components.
        Exposes a user weight that ramps up over 4 epochs after the user deposits into 
        any of the staking components.
"""

from ethereum.ercs import IERC20

interface IComponent:
    def upstream() -> address: view

interface IHooks:
    def on_transfer(_caller: address, _from: address, _to: address, _supply: uint256, _prev_staked_from: uint256, _prev_staked_to: uint256, _value: uint256): nonpayable
    def on_stake(_caller: address, _account: address, _prev_supply: uint256, _prev_staked: uint256, _value: uint256): nonpayable
    def on_unstake(_account: address, _prev_supply: uint256, _prev_staked: uint256, _value: uint256): nonpayable

interface IWeightAggregator:
    def supply() -> uint256: view
    def staked(_account: address) -> uint256: view
    def total_weight() -> uint256: view
    def weight(_account: address) -> uint256: view

implements: IHooks
implements: IWeightAggregator

genesis: public(immutable(uint256))
management: public(address)
pending_management: public(address)
downstream: public(IHooks)
num_components: public(uint256)
components: public(HashMap[uint256, address]) # idx => component
depositors: public(HashMap[address, address]) # component => depositor
prev_packed_supply: public(uint256)
packed_supply: public(uint256)
prev_packed_staked: public(HashMap[address, uint256])
packed_staked: public(HashMap[address, uint256])

event Activate:
    supply: uint256

event AddComponent:
    component: indexed(address)
    depositor: indexed(address)

event RemoveComponent:
    component: indexed(address)

event SetDownstream:
    downstream: indexed(address)

event PendingManagement:
    management: indexed(address)

event SetManagement:
    management: indexed(address)

MAX_NUM_COMPONENTS: constant(uint256) = 32
EPOCH_LENGTH: constant(uint256) = 14 * 24 * 60 * 60
RAMP_LENGTH: constant(uint256) = 4 * EPOCH_LENGTH
INCREMENT: constant(bool) = True
DECREMENT: constant(bool) = False
EPOCH_MASK: constant(uint256) = 2**16 - 1
TIME_MASK: constant(uint256) = 2**40 - 1
AMOUNT_MASK: constant(uint256) = 2**100 - 1

@deploy
def __init__(_genesis: uint256):
    """
    @notice Constructor
    @param _genesis Genesis timestamp
    """
    assert block.timestamp >= _genesis + RAMP_LENGTH
    genesis = _genesis
    self.management = msg.sender

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
def supply() -> uint256:
    """
    @notice Query the supply, the sum of all staked balances in all components
    @return Supply
    """
    return self._supply(False)

@external
@view
def staked(_account: address) -> uint256:
    """
    @notice Query the staked amount of a specific account
    @param _account Account to query for
    @return Staked amount
    """
    return self._staked(_account, False)

@external
@view
def total_weight() -> uint256:
    """
    @notice Query the total weight, which is an upper bound on the sum of all user weights
            in the epoch. Snapshotted at the beginning of every epoch.
    @return Total weight
    """
    return self._supply(True)

@external
@view
def weight(_account: address) -> uint256:
    """
    @notice Query the weight of a specific user. The weight ramps up over time after deposits
            and is snapshotted at the beginning of every epoch.
    @param _account Account to query for
    @return Staked amount
    """
    return self._staked(_account, True)

@external
def on_transfer(_caller: address, _from: address, _to: address, _: uint256, _prev_staked_from: uint256, _prev_staked_to: uint256, _amount: uint256):
    """
    @notice Triggered by the hook upon transfer of tokens
    @param _caller Originator of the transfer
    @param _from Sender of the token
    @param _to Recipient of the tokens
    @param _ Total token supply (unused)
    @param _prev_staked_from Staked balance of sender before transfer
    @param _prev_staked_to Staked balance of recipient before transfer
    @param _amount Amount of tokens to transfer
    """
    assert self.depositors[msg.sender] != empty(address)
    agg_supply: uint256 = self._unpack(self.packed_supply)[2]
    prev_agg_staked_from: uint256 = self._update_staked(_from, _prev_staked_from, _amount, DECREMENT)
    prev_agg_staked_to: uint256 = self._update_staked(_to, _prev_staked_to, _amount, INCREMENT)
    if self.downstream.address != empty(address):
        # the values in the hook represent a single component, but we forward the aggregated amounts to the downstream hook
        extcall self.downstream.on_transfer(_caller, _from, _to, agg_supply, prev_agg_staked_from, prev_agg_staked_to, _amount)

@external
def on_stake(_caller: address, _account: address, _: uint256, _prev_staked: uint256, _amount: uint256):
    """
    @notice Triggered by the hook upon staking of tokens
    @param _caller Originator of the tokens
    @param _account Recipient of the staked tokens
    @param _ Total token supply before stake (unused)
    @param _prev_staked Staked balance of recipient before stake
    @param _amount Amount of tokens to stake
    """
    assert self.depositors[msg.sender] != empty(address)
    prev_agg_supply: uint256 = self._update_supply(_amount, INCREMENT)
    prev_agg_staked: uint256 = self._update_staked(_account, _prev_staked, _amount, INCREMENT)
    if self.downstream.address != empty(address):
        # the values in the hook represent a single component, but we forward the aggregated amounts to the downstream hook
        extcall self.downstream.on_stake(_caller, _account, prev_agg_supply, prev_agg_staked, _amount)

@external
def on_unstake(_account: address, _: uint256, _prev_staked: uint256, _amount: uint256):
    """
    @notice Triggered by the hook upon unstaking of tokens
    @param _account Originator of the staked tokens
    @param _ Total token supply before unstake (unused)
    @param _prev_staked Staked balance of originator before unstake
    @param _amount Amount of tokens to unstake
    """
    assert self.depositors[msg.sender] != empty(address)
    prev_agg_supply: uint256 = self._update_supply(_amount, DECREMENT)
    prev_agg_staked: uint256 = self._update_staked(_account, _prev_staked, _amount, DECREMENT)
    if self.downstream.address != empty(address):
        # the values in the hook represent a single component, but we forward the aggregated amounts to the downstream hook
        extcall self.downstream.on_unstake(_account, prev_agg_supply, prev_agg_staked, _amount)

@external
def activate(_components: DynArray[address, 4]):
    """
    @notice Activate the aggregator by setting the components and calculating the total supply
    @param _components List of middleware components
    @dev Can only be called by management
    @dev Activation should be done atomically with setting the aggregator as hook recipient to all the components
    """
    assert msg.sender == self.management
    assert self.packed_supply == 0

    i: uint256 = 0
    supply: uint256 = 0
    self.num_components = len(_components)
    for component: address in _components:
        depositor: address = staticcall IComponent(component).upstream()
        self.components[i] = component
        self.depositors[component] = depositor
        log AddComponent(component=component, depositor=depositor)

        supply += staticcall IERC20(depositor).totalSupply()
        i += 1

    self.packed_supply = self._pack(self._epoch() - 1, 0, supply, 0)
    log Activate(supply=supply)

@external
def add_component(_component: address, _depositor: address) -> uint256:
    """
    @notice Add a new component
    @param _component Component address
    @param _depositor Corresponding depositor address
    @return Component index
    @dev Can only be called by management
    @dev Caller is responsible for ensuring consistency between the supply and balances before and after the call
    """
    assert msg.sender == self.management
    assert self.packed_supply > 0
    idx: uint256 = self.num_components
    assert idx < MAX_NUM_COMPONENTS
    assert _component != empty(address)
    assert self.depositors[_component] == empty(address)
    assert _depositor != empty(address)

    self.components[idx] = _component
    self.depositors[_component] = _depositor
    self.num_components = idx + 1

    log AddComponent(component=_component, depositor=_depositor)
    return idx

@external
def remove_component(_idx: uint256):
    """
    @notice Remove an existing component
    @param _idx Component index
    @dev Can only be called by management
    @dev Caller is responsible for ensuring consistency between the supply and balances before and after the call
    """
    assert msg.sender == self.management
    last: uint256 = self.num_components - 1
    assert _idx <= last

    component: address = self.components[_idx]
    self.depositors[component] = empty(address)
    if _idx != last:
        self.components[_idx] = self.components[last]
    self.components[last] = empty(address)
    self.num_components = last
    log RemoveComponent(component=component)

@external
def set_downstream(_downstream: address):
    """
    @notice Set the downstream address where hooks are forwarded to
    @param _downstream Downstream hook address
    @dev Can only be called by management
    """
    assert msg.sender == self.management

    self.downstream = IHooks(_downstream)
    log SetDownstream(downstream=_downstream)

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
@view
def _supply(_snapshot: bool) -> uint256:
    """
    @notice Get the (snapshotted) total staked amount
    """
    epoch: uint256 = 0
    time: uint256 = 0
    supply: uint256 = 0
    ramping: uint256 = 0
    epoch, time, supply, ramping = self._unpack(self.packed_supply)

    if _snapshot and epoch == self._epoch():
        # supply changed this epoch, use snapshot
        epoch, time, supply, ramping = self._unpack(self.prev_packed_supply)

    return supply

@internal
@view
def _staked(_account: address, _weighted: bool) -> uint256:
    """
    @notice Get the (weighted) staked amount for an account
    """
    epoch: uint256 = 0
    time: uint256 = 0
    staked: uint256 = 0
    ramping: uint256 = 0
    epoch, time, staked, ramping = self._unpack(self.packed_staked[_account])

    if epoch == 0:
        # no update yet, calculate from components
        return self._calculate_staked(_account, empty(address), 0)

    if not _weighted:
        return staked

    if epoch == self._epoch():
        # staked changed this epoch
        prev_time: uint256 = 0
        prev_staked: uint256 = 0
        prev_ramping: uint256 = 0
        epoch, prev_time, prev_staked, prev_ramping = self._unpack(self.prev_packed_staked[_account])
        if staked > prev_staked:
            # use previous value only if the stake has increased
            time = prev_time
            staked = prev_staked
            ramping = prev_ramping

    # snapshot at beginning of the epoch
    time = genesis + self._epoch() * EPOCH_LENGTH - time
    return staked - ramping + ramping * min(time, RAMP_LENGTH) // RAMP_LENGTH

@internal
@view
def _calculate_staked(_account: address, _skip: address, _prev: uint256) -> uint256:
    """
    @notice Calculate the staked amount of an account by summing the balances in each depositor.
            Since the upstream hook might have fired after the state change, we avoid getting its
            component balance and instead rely on the supplied value instead
    """
    num_components: uint256 = self.num_components
    assert num_components > 0

    staked: uint256 = _prev
    for i: uint256 in range(num_components, bound=MAX_NUM_COMPONENTS):
        component: address = self.components[i]
        if component == _skip:
            # avoid double counting if triggered by a component hook
            continue
        depositor: address = self.depositors[component]
        staked += staticcall IERC20(depositor).balanceOf(_account)
    return staked

@internal
def _update_supply(_amount: uint256, _increment: bool) -> uint256:
    """
    @notice Update the total staked amount. Returns previous supply
    """

    epoch: uint256 = 0
    time: uint256 = 0
    supply: uint256 = 0
    ramping: uint256 = 0
    epoch, time, supply, ramping = self._unpack(self.packed_supply)
    prev_supply: uint256 = supply

    if _increment == INCREMENT:
        supply += _amount
    else:
        supply -= _amount

    current_epoch: uint256 = self._epoch()
    if current_epoch > epoch:
        self.prev_packed_supply = self.packed_supply
    self.packed_supply = self._pack(current_epoch, 0, supply, 0)

    return prev_supply

@internal
def _update_staked(_account: address, _prev: uint256, _amount: uint256, _increment: bool) -> uint256:
    """
    @notice Update the staked amount of an account. Returns previous staked amount
    """
    epoch: uint256 = 0
    time: uint256 = 0
    staked: uint256 = 0
    ramping: uint256 = 0
    epoch, time, staked, ramping = self._unpack(self.packed_staked[_account])

    if epoch == 0:
        # first update since activation, calculate from components
        epoch = 1
        time = 0
        staked = self._calculate_staked(_account, msg.sender, _prev)
        self.packed_staked[_account] = self._pack(1, 0, staked, 0)
    prev_staked: uint256 = staked

    if _increment == INCREMENT:
        staked += _amount
        # remove already ramped amount and add new amount
        ramping = ramping * (RAMP_LENGTH - min(block.timestamp - time, RAMP_LENGTH)) // RAMP_LENGTH + _amount
        time = block.timestamp
    else:
        new_staked: uint256 = staked - _amount
        # remove a proportional amount from ramp
        ramping = ramping * new_staked // staked
        staked = new_staked

    current_epoch: uint256 = self._epoch()
    if current_epoch > epoch:
        self.prev_packed_staked[_account] = self.packed_staked[_account]
    self.packed_staked[_account] = self._pack(current_epoch, time, staked, ramping)

    return prev_staked

@internal
@pure
def _pack(_epoch: uint256, _time: uint256, _amount: uint256, _ramping: uint256) -> uint256:
    """
    @notice Pack four values into a single storage slot
    """
    assert _epoch <= EPOCH_MASK and _time <= TIME_MASK and _amount <= AMOUNT_MASK and _ramping <= AMOUNT_MASK
    return (_epoch << 240) | (_time << 200) | (_amount << 100) | _ramping

@internal
@pure
def _unpack(_packed: uint256) -> (uint256, uint256, uint256, uint256):
    """
    @notice Unpack four values from a single storage slot
    """
    return _packed >> 240, (_packed >> 200) & TIME_MASK, (_packed >> 100) & AMOUNT_MASK, _packed & AMOUNT_MASK
