# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Snapshot measure
@author Yearn Finance
@license GNU AGPLv3
@notice Measures the voting weight by summing up contributions from
        stYFI, staked veYFI liquid locker tokens and migrated veYFI
"""

from ethereum.ercs import IERC20

interface IWeightAggregator:
    def genesis() -> uint256: view
    def weight(_account: address) -> uint256: view

interface VeRewardDistributor:
    def last_claimed(_account: address) -> uint256: view
    def check_lock(_account: address) -> (uint256, uint256): view

event SetYBC:
    ybc: address

genesis: public(immutable(uint256))
styfix: public(immutable(address))
aggregator: public(immutable(IWeightAggregator))
ve_reward_distributor: public(immutable(VeRewardDistributor))
ybc: public(address)

EPOCH_LENGTH: constant(uint256) = 14 * 24 * 60 * 60

@deploy
def __init__(_styfix: address, _aggregator: address, _verd: address):
    """
    @notice Constructor
    @param _styfix stYFIx address
    @param _aggregator Weight aggregator address
    @param _verd veYFI reward distributor address
    """
    styfix = _styfix
    aggregator = IWeightAggregator(_aggregator)
    genesis = staticcall aggregator.genesis()
    ve_reward_distributor = VeRewardDistributor(_verd)
    self.ybc = msg.sender

@external
@view
def balanceOf(_account: address) -> uint256:
    """
    @notice Query voting weight of a specific account
    @param _account Account to query voting weight for
    @return Voting weight
    """
    if _account == styfix:
        return 0

    weight: uint256 = self._weight(_account)
    if _account == self.ybc:
        weight += self._weight(styfix)
    return weight

@internal
@view
def _weight(_account: address) -> uint256:
    """
    @notice Compute voting weight of an account by summing up contributions from 
            stYFI, staked liquid locker tokens and migrated veYFI
    """
    # stYFI + llYFI
    weight: uint256 = staticcall aggregator.weight(_account)

    # migrated veYFI
    if staticcall ve_reward_distributor.last_claimed(_account) > 0:
        lock_amount: uint256 = 0
        unlock_time: uint256 = 0
        lock_amount, unlock_time = staticcall ve_reward_distributor.check_lock(_account)
        
        epoch_end: uint256 = genesis + ((block.timestamp - genesis) // EPOCH_LENGTH + 1) * EPOCH_LENGTH
        if unlock_time >= epoch_end:
            weight += lock_amount

    return weight

@external
def set_ybc(_ybc: address):
    """
    @notice Set an address as the YBC
    @param _ybc New YBC address
    @dev Can only be called by current YBC address
    """
    assert msg.sender == self.ybc
    self.ybc = _ybc
    log SetYBC(ybc=_ybc)
