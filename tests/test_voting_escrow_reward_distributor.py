from ape import reverts
from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
COMPONENTS_SENTINEL = '0x1111111111111111111111111111111111111111'
UNIT = 10**18
PRECISION = 10**30
DUST = 10**12

@fixture
def veyfi(project, deployer):
    return project.MockVotingEscrow.deploy(sender=deployer)

@fixture
def snapshot(project, deployer, veyfi):
    return project.VotingEscrowSnapshot.deploy(veyfi, sender=deployer)

@fixture
def ve_distributor(project, deployer, reward, distributor, genesis, snapshot):
    vrd = project.VotingEscrowRewardDistributor.deploy(genesis, reward, sender=deployer)
    vrd.set_distributor(distributor, sender=deployer)
    vrd.set_snapshot(snapshot, sender=deployer)
    
    distributor.add_component(vrd, COMPONENTS_SENTINEL, sender=deployer)

    return vrd

def test_rewards(chain, deployer, alice, bob, reward, distributor, genesis, veyfi, snapshot, ve_distributor):
    ve_distributor.set_claimer(deployer, True, sender=deployer)

    unlock = genesis + 4 * EPOCH_LENGTH
    snapshot.set_snapshot(alice, DUST, 8, unlock, sender=deployer)
    snapshot.set_snapshot(bob, 2 * DUST, 8, unlock, sender=deployer)
    assert snapshot.locked(alice).amount == 0
    veyfi.set_locked(alice, DUST, unlock, sender=deployer)
    veyfi.set_locked(bob, 2 * DUST, unlock, sender=deployer)
    assert snapshot.locked(alice).amount == DUST

    chain.pending_timestamp = genesis

    # add some rewards
    reward.mint(alice, UNIT, sender=alice)
    reward.approve(distributor, UNIT, sender=alice)
    distributor.deposit(0, UNIT, sender=alice)

    ve_distributor.migrate(sender=alice)
    slope = DUST // 104
    assert ve_distributor.total_weights(0) == (2 * DUST + 8 * slope, slope)

    ve_distributor.migrate(sender=bob)
    slope2 = 2 * DUST // 104
    assert ve_distributor.total_weights(0) == (4 * DUST + 8 * slope + 8 * slope2, slope + slope2)

    # fast forward to middle of epoch 
    ts = genesis + EPOCH_LENGTH * 3 // 2
    chain.pending_timestamp = ts

    rewards = ve_distributor.claim(alice, sender=deployer).return_value
    assert ve_distributor.rewards(0) == UNIT

    epoch_rewards = UNIT * (DUST + 8 * slope) // (4 * DUST + 8 * slope + 8 * slope2)
    assert rewards == epoch_rewards // 2

def test_unlock(chain, deployer, alice, reward, distributor, genesis, veyfi, snapshot, ve_distributor):
    ve_distributor.set_claimer(deployer, True, sender=deployer)

    unlock = genesis + 2 * EPOCH_LENGTH
    snapshot.set_snapshot(alice, DUST, 4, unlock, sender=deployer)
    veyfi.set_locked(alice, DUST, unlock, sender=deployer)
    
    chain.pending_timestamp = genesis
    ve_distributor.migrate(sender=alice)

    # add some rewards
    reward.mint(alice, 10 * UNIT, sender=alice)
    reward.approve(distributor, 10 * UNIT, sender=alice)
    for i in range(10):
        distributor.deposit(i, UNIT, sender=alice)

    slope = DUST // 104

    # epoch 0
    assert ve_distributor.total_weights(0) == (2 * DUST + 4 * slope, slope)

    # beginning of epoch 1
    chain.pending_timestamp = genesis + EPOCH_LENGTH
    ve_distributor.sync_total_weight(1, sender=deployer)
    assert ve_distributor.total_weights(1) == (2 * DUST + 3 * slope, slope)

    # beginning of epoch 2 - fully streamed epoch 1 rewards
    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH
    ve_distributor.sync_total_weight(2, sender=deployer)
    assert ve_distributor.total_weights(2) == (DUST, 0)

    rewards = UNIT * (DUST + 4 * slope) // (2 * DUST + 4 * slope)
    with chain.isolate():
        assert ve_distributor.claim(alice, sender=deployer).return_value == rewards

    # beginning of epoch 3 - fully streamed epoch 2 rewards
    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    rewards += UNIT * (DUST + 3 * slope) // (2 * DUST + 3 * slope)
    with chain.isolate():
        assert ve_distributor.claim(alice, sender=deployer).return_value == rewards

    # beginning of epoch 4 - no additional rewards have been streamed
    chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
    with chain.isolate():
        assert ve_distributor.claim(alice, sender=deployer).return_value == rewards
