# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Reward Distributor
@author Yearn Finance
@license GNU AGPLv3
@notice Distributes token rewards epoch-by-epoch to a set of preconfigured components, 
        proportionally to their self reported weight.
        Rewards can be deposited for future epochs and optionally pulled from another contract.
"""

from ethereum.ercs import IERC20

interface IComponent:
    def sync_total_weight(_epoch: uint256) -> uint256: nonpayable

interface IPull:
    def pull(_epoch: uint256) -> uint256: nonpayable

struct ComponentData:
    epoch: uint256
    next: address

genesis: public(immutable(uint256))
token: public(immutable(IERC20))
management: public(address)
pending_management: public(address)

pull: public(IPull)
num_components: public(uint256)
linked_components: public(HashMap[address, ComponentData])

last_epoch: public(uint256)
epoch_rewards: public(HashMap[uint256, uint256]) # epoch => rewards
epoch_total_weight: public(HashMap[uint256, uint256]) # epoch => total weight
epoch_weights: public(HashMap[address, HashMap[uint256, uint256]]) # component => epoch => weight

event FinalizeEpoch:
    epoch: uint256
    total_weight: uint256
    rewards: uint256

event AddRewards:
    depositor: address
    epoch: uint256
    rewards: uint256

event SetPull:
    pull: address

event AddComponent:
    component: address
    after: address

event RemoveComponent:
    component: address

event PendingManagement:
    management: indexed(address)

event SetManagement:
    management: indexed(address)

MAX_NUM_COMPONENTS: constant(uint256) = 32
COMPONENTS_SENTINEL: constant(address) = 0x1111111111111111111111111111111111111111
GLOBAL_CURSOR: constant(address) = empty(address)
EPOCH_LENGTH: constant(uint256) = 14 * 24 * 60 * 60

@deploy
def __init__(_genesis: uint256, _token: address):
    """
    @notice Constructor
    @param _genesis Genesis timestamp
    @param _token The address of the reward token
    """
    genesis = _genesis
    token = IERC20(_token)

    self.management = msg.sender
    self.linked_components[COMPONENTS_SENTINEL] = ComponentData(epoch=0, next=COMPONENTS_SENTINEL)

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
def rewards(_component: address, _epoch: uint256) -> uint256:
    """
    @notice Query the rewards for a specific component
    @param _component The component address
    @param _epoch The epoch number
    @return The amount of reward tokens allocated to the component
    """
    return self._rewards(_component, _epoch)[1]

@external
def claim() -> (uint256, uint256, uint256):
    """
    @notice Claim epoch rewards in order
    @return A tuple with the epoch number, the previous reported weight and the token rewards
    @dev Can only be called by an address that has been a component at one point
    """
    # weights and amounts are only finalized at the end of the epoch
    current: uint256 = self._epoch()
    assert self._sync(current)

    # make sure the caller is a component that was enabled at some point
    data: ComponentData = self.linked_components[msg.sender]
    epoch: uint256 = data.epoch
    assert epoch > 0 or data.next != empty(address)
    assert epoch < current

    weight: uint256 = 0
    rewards: uint256 = 0
    weight, rewards = self._rewards(msg.sender, epoch)
    self.linked_components[msg.sender].epoch = epoch + 1

    assert extcall token.transfer(msg.sender, rewards, default_return_value=True)

    return epoch, weight, rewards

@external
def sync() -> bool:
    """
    @notice Finalize weights and rewards for completed epochs
    @return True: fully synchronized, False: not fully synchronized
    """
    return self._sync(self._epoch())

@external
def deposit(_epoch: uint256, _amount: uint256):
    """
    @notice Deposit rewards for distribution in a future epoch
    @param _epoch Epoch number to ascribe rewards to
    @param _amount Amount of reward tokens to deposit
    """
    assert _epoch >= self._epoch()

    self.epoch_rewards[_epoch] += _amount
    assert extcall token.transferFrom(msg.sender, self, _amount, default_return_value=True)
    log AddRewards(depositor=msg.sender, epoch=_epoch, rewards=_amount)

@external
def set_pull(_pull: address):
    """
    @notice Set the address to pull future rewards from
    @param _pull Address to pull from. Set to zero address if none
    @dev Can only be called by management
    """
    assert msg.sender == self.management

    self.pull = IPull(_pull)
    log SetPull(pull=_pull)

@external
def add_component(_component: address, _after: address):
    """
    @notice Add a component
    @param _component Address of the component to add
    @param _after Address in the list to add the component after
    @dev Can only be called by management
    """
    assert msg.sender == self.management
    assert _component != empty(address)
    assert self.linked_components[_component].next == empty(address)
    next: address = self.linked_components[_after].next
    assert next != empty(address)
    num_components: uint256 = self.num_components
    assert num_components < MAX_NUM_COMPONENTS

    self.num_components = num_components + 1
    self.linked_components[_after].next = _component
    epoch: uint256 = 0
    if block.timestamp >= genesis + EPOCH_LENGTH:
        epoch = self._epoch() - 1
    self.linked_components[_component] = ComponentData(epoch=epoch, next=next)
    log AddComponent(component=_component, after=_after)

@external
def remove_component(_component: address, _previous: address):
    """
    @notice Remove a component
    @param _component Address of the component to remove
    @param _previous Address in the list before the component
    @dev Can only be called by management
    """
    assert msg.sender == self.management
    assert _component != empty(address) and _previous != empty(address)
    assert self.linked_components[_previous].next == _component
    next: address = self.linked_components[_component].next
    assert next != empty(address)

    self.num_components -= 1
    self.linked_components[_previous].next = next
    self.linked_components[_component].next = empty(address)
    log RemoveComponent(component=_component)

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
def _sync(_current: uint256) -> bool:
    """
    @notice Finalize weights and rewards for completed epochs in order
    """
    epoch: uint256 = self.last_epoch

    if epoch == _current:
        return True

    pull: IPull = self.pull
    for i: uint256 in range(32):
        if epoch == _current:
            break
        
        # calculate sum of weights of all components
        total_weight: uint256 = 0
        component: address = COMPONENTS_SENTINEL
        for j: uint256 in range(MAX_NUM_COMPONENTS):
            component = self.linked_components[component].next
            if component == COMPONENTS_SENTINEL:
                break

            weight: uint256 = extcall IComponent(component).sync_total_weight(epoch)
            self.epoch_weights[component][epoch] = weight
            total_weight += weight
        self.epoch_total_weight[epoch] = total_weight

        # try to pull in rewards
        if pull.address != empty(address):
            pulled: uint256 = extcall pull.pull(epoch)
            if pulled > 0:
                assert extcall token.transferFrom(pull.address, self, pulled, default_return_value=True)
                self.epoch_rewards[epoch] += pulled
                log AddRewards(depositor=pull.address, epoch=epoch, rewards=pulled)

        rewards: uint256 = self.epoch_rewards[epoch]
        if total_weight == 0:
            # no weight, allocate rewards to next epoch instead
            self.epoch_rewards[epoch] = 0
            self.epoch_rewards[epoch + 1] += rewards
            log AddRewards(depositor=self, epoch=epoch + 1, rewards=rewards)
            rewards = 0

        log FinalizeEpoch(epoch=epoch, total_weight=total_weight, rewards=rewards)
        epoch += 1

    self.last_epoch = epoch
    return epoch == _current

@internal
@view
def _rewards(_component: address, _epoch: uint256) -> (uint256, uint256):
    """
    @notice Compute rewards for a specific component in a specific epoch
    """
    total: uint256 = self.epoch_total_weight[_epoch]
    if total == 0:
        return 0, 0
    weight: uint256 = self.epoch_weights[_component][_epoch]
    return weight, self.epoch_rewards[_epoch] * weight // total
