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

interface VeRewardDistributor:
    def last_claimed(_account: address) -> uint256: view
    def check_lock(_account: address) -> (uint256, uint256): view

event SetYBC:
    ybc: address

styfi: public(immutable(IERC20))
styfix: public(immutable(address))
liquid_locker_depositors: public(immutable(IERC20[3]))
ve_reward_distributor: public(immutable(VeRewardDistributor))
ybc: public(address)

@deploy
def __init__(_styfi: address, _styfix: address, _depositors: address[3], _verd: address):
    """
    @notice Constructor
    @param _styfi stYFI address
    @param _styfix stYFIx address
    @param _depositors liquid locker token depositor addresses
    @param _verd veYFI reward distributor address
    """
    styfi = IERC20(_styfi)
    styfix = _styfix
    liquid_locker_depositors = [IERC20(_depositors[0]), IERC20(_depositors[1]), IERC20(_depositors[2])]
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

    # stYFI
    weight: uint256 = staticcall styfi.balanceOf(_account)

    # liquid lockers
    weight += staticcall liquid_locker_depositors[0].balanceOf(_account) + \
              staticcall liquid_locker_depositors[1].balanceOf(_account) + \
              staticcall liquid_locker_depositors[2].balanceOf(_account)

    # migrated veYFI
    if staticcall ve_reward_distributor.last_claimed(_account) > 0:
        lock_amount: uint256 = 0
        unlock_time: uint256 = 0
        lock_amount, unlock_time = staticcall ve_reward_distributor.check_lock(_account)
        if block.timestamp < unlock_time:
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
