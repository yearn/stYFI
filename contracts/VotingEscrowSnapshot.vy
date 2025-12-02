# pragma version 0.4.2
# pragma optimize gas
# pragma evm-version cancun
"""
@title Voting Escrow Snapshot
@author Yearn Finance
@license GNU AGPLv3
@notice Contains a set of snapshotted veYFI locks.
"""

struct Snapshot:
    amount: uint256
    boost_epochs: uint256
    unlock_time: uint256

interface ISnapshot:
    def locked(_account: address) -> Snapshot: view

interface IVotingEscrow:
    def locked(_account: address) -> (uint256, uint256): view

implements: ISnapshot

veyfi: public(immutable(IVotingEscrow))
management: public(address)

snapshot: public(HashMap[address, Snapshot])

event SetSnapshot:
    account: indexed(address)
    amount: uint256
    boost: uint256
    unlock: uint256

event SetManagement:
    management: indexed(address)

EPOCH_LENGTH: constant(uint256) = 14 * 24 * 60 * 60

@deploy
def __init__(_veyfi: address):
    """
    @notice Constructor
    @param _veyfi veYFI address
    """
    veyfi = IVotingEscrow(_veyfi)
    self.management = msg.sender

@external
@view
def locked(_account: address) -> Snapshot:
    """
    @notice Query snapshotted lock of an account
    @param _account Account to get lock for
    @return Struct containing lock information
    @dev Only returns snapshot if not already exited out of the position in the present
    """
    snapshot: Snapshot = self.snapshot[_account]
    amount: uint256 = 0
    end: uint256 = 0
    amount, end = staticcall veyfi.locked(_account)
    if amount < snapshot.amount or end < snapshot.unlock_time:
        return empty(Snapshot)
    return snapshot

@external
def set_snapshot(_account: address, _amount: uint256, _boost: uint256, _unlock: uint256):
    """
    @notice Set a veYFI position snapshot
    @param _account Account to set snapshot for
    @param _amount Amount of YFI in the lock
    @param _boost Boost at time of snapshot, in epochs
    @param _unlock Timestamp of unlock
    @dev Can only called by management
    """
    assert msg.sender == self.management

    self.snapshot[_account] = Snapshot(amount=_amount, boost_epochs=_boost, unlock_time=_unlock)
    log SetSnapshot(account=_account, amount=_amount, boost=_boost, unlock=_unlock)

@external
def set_management(_management: address):
    """
    @notice Set the new management address
    @param _management New management address
    """
    assert msg.sender == self.management

    self.management = _management
    log SetManagement(management=_management)
