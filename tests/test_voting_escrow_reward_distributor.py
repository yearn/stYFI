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
def ve_distributor(project, deployer, reward, distributor, snapshot):
    vrd = project.VotingEscrowRewardDistributor.deploy(distributor, reward, sender=deployer)
    vrd.set_snapshot(snapshot, sender=deployer)
    
    distributor.add_component(vrd, COMPONENTS_SENTINEL, sender=deployer)

    return vrd

@fixture
def claimer(project, deployer, reward, ve_distributor):
    claimer = project.RewardClaimer.deploy(reward, sender=deployer)
    claimer.add_component(ve_distributor, sender=deployer)
    ve_distributor.set_claimer(claimer, True, sender=deployer)
    return claimer

def test_rewards(chain, deployer, alice, bob, charlie, reward, distributor, genesis, veyfi, snapshot, ve_distributor, claimer):
    # rewards are distributed according to each lock's boosted weight
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
    epoch_rewards = UNIT * (DUST + 8 * slope) // (4 * DUST + 8 * slope + 8 * slope2)

    with chain.isolate():
        # rewards can be claimed through the RewardClaimer
        chain.pending_timestamp = ts
        assert claimer.claim(charlie, sender=alice).return_value == epoch_rewards // 2
        assert reward.balanceOf(charlie) == epoch_rewards // 2

    chain.pending_timestamp = ts
    rewards = ve_distributor.claim(alice, sender=deployer).return_value
    assert rewards == epoch_rewards // 2
    assert reward.balanceOf(deployer) == epoch_rewards // 2
    assert ve_distributor.rewards(0) == UNIT

def test_unlock(chain, deployer, alice, reward, distributor, genesis, veyfi, snapshot, ve_distributor):
    # expired locks update weight accounting properly
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
        chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH
        assert ve_distributor.claim(alice, sender=deployer).return_value == rewards
        assert reward.balanceOf(deployer) == rewards

    # beginning of epoch 3 - fully streamed epoch 2 rewards
    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    rewards += UNIT * (DUST + 3 * slope) // (2 * DUST + 3 * slope)
    with chain.isolate():
        assert ve_distributor.claim(alice, sender=deployer).return_value == rewards
        assert reward.balanceOf(deployer) == rewards

    # beginning of epoch 4 - no additional rewards have been streamed
    chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
    with chain.isolate():
        assert ve_distributor.claim(alice, sender=deployer).return_value == rewards
        assert reward.balanceOf(deployer) == rewards

def test_reclaim(chain, deployer, alice, reward, distributor, genesis, veyfi, snapshot, ve_distributor):
    # rewards can be reclaimed after some time
    ve_distributor.set_claimer(deployer, True, sender=deployer)
    ve_distributor.set_reward_expiration(3, 0, deployer, sender=deployer)

    unlock = genesis + 4 * EPOCH_LENGTH
    snapshot.set_snapshot(alice, DUST, 8, unlock, sender=deployer)
    veyfi.set_locked(alice, DUST, unlock, sender=deployer)

    chain.pending_timestamp = genesis

    # add some rewards
    reward.mint(alice, 100 * UNIT, sender=alice)
    reward.approve(distributor, 100 * UNIT, sender=alice)
    for i in range(10):
        distributor.deposit(i, UNIT, sender=alice)

    ve_distributor.migrate(sender=alice)
    slope = DUST // 104

    with chain.isolate():
        # in middle of epoch 4, we are able to claim reward to middle of epoch 4-3=1
        ts = genesis + EPOCH_LENGTH * 9 // 2
        chain.pending_timestamp = ts
        rewards = ve_distributor.reclaim(alice, sender=deployer).return_value[0]
        expect = UNIT // 2 * (DUST + 8 * slope) // (2 * DUST + 8 * slope)
        assert rewards == expect
        assert reward.balanceOf(deployer) == expect
        assert ve_distributor.last_claimed(alice) == ts - 3 * EPOCH_LENGTH

        # and at end of epoch 4, we are able to claim reward to end of epoch 1
        ts = genesis + EPOCH_LENGTH * 5
        chain.pending_timestamp = ts
        rewards = ve_distributor.reclaim(alice, sender=deployer).return_value[0]
        assert rewards == expect
        assert reward.balanceOf(deployer) == 2 * expect

    with chain.isolate():
        # in middle of epoch 5, we are able to claim reward to middle of epoch 5-3=3
        ts = genesis + EPOCH_LENGTH * 11 // 2
        chain.pending_timestamp = ts
        rewards = ve_distributor.reclaim(alice, sender=deployer).return_value[0]
        expect = UNIT * (DUST + 8 * slope) // (2 * DUST + 8 * slope) + UNIT // 2 * (DUST + 7 * slope) // (2 * DUST + 7 * slope)
        assert rewards == expect
        assert reward.balanceOf(deployer) == expect
        assert ve_distributor.last_claimed(alice) == ts - 3 * EPOCH_LENGTH

def test_report(chain, deployer, alice, bob, charlie, reward, distributor, genesis, veyfi, snapshot, ve_distributor):
    # early exits can be reported
    unlock = genesis + 4 * EPOCH_LENGTH
    snapshot.set_snapshot(alice, DUST, 8, unlock, sender=deployer)
    snapshot.set_snapshot(bob, 2 * DUST, 8, unlock + EPOCH_LENGTH, sender=deployer)
    veyfi.set_locked(alice, DUST, unlock, sender=deployer)
    veyfi.set_locked(bob, 2 * DUST, unlock + EPOCH_LENGTH, sender=deployer)

    chain.pending_timestamp = genesis

    # add some rewards
    reward.mint(alice, 10 * UNIT, sender=alice)
    reward.approve(distributor, 10 * UNIT, sender=alice)
    for i in range(10):
        distributor.deposit(i, UNIT, sender=alice)

    ve_distributor.migrate(sender=alice)
    ve_distributor.migrate(sender=bob)
    slope = DUST // 104
    slope2 = 2 * DUST // 104

    # simulate early exit
    veyfi.set_locked(alice, 0, 0, sender=deployer)

    # fast forward to middle of epoch 2
    chain.pending_timestamp = genesis + EPOCH_LENGTH * 5 // 2

    # when reporting, all rewards until the end of the epoch will be reclaimed
    epoch1_rewards = UNIT * (DUST + 8 * slope) // (4 * DUST + 8 * slope + 8 * slope2)
    epoch2_rewards = UNIT * (DUST + 7 * slope) // (4 * DUST + 7 * slope + 7 * slope2)

    ve_distributor.sync_total_weight(2, sender=deployer)
    assert ve_distributor.total_weights(2) == (4 * DUST + 6 * slope + 6 * slope2, slope + slope2)
    assert ve_distributor.unlocks(4) == (DUST + 4 * slope, slope)

    reclaimed = ve_distributor.report(alice, sender=charlie).return_value[0]
    assert reclaimed == epoch1_rewards + epoch2_rewards
    assert reward.balanceOf(deployer) == reclaimed
    assert ve_distributor.locks(alice).amount == 0
    assert ve_distributor.total_weights(2) == (3 * DUST + 6 * slope2, slope2)
    assert ve_distributor.unlocks(4) == (0, 0)
    assert ve_distributor.last_claimed(alice) == genesis + EPOCH_LENGTH * 3

def test_report_partial(chain, deployer, alice, bob, charlie, reward, distributor, genesis, veyfi, snapshot, ve_distributor):
    # early exits can be reported but only reclaim unclaimed rewards
    ve_distributor.set_claimer(bob, True, sender=deployer)

    unlock = genesis + 4 * EPOCH_LENGTH
    snapshot.set_snapshot(alice, DUST, 8, unlock, sender=deployer)
    snapshot.set_snapshot(bob, 2 * DUST, 8, unlock + EPOCH_LENGTH, sender=deployer)
    veyfi.set_locked(alice, DUST, unlock, sender=deployer)
    veyfi.set_locked(bob, 2 * DUST, unlock + EPOCH_LENGTH, sender=deployer)

    chain.pending_timestamp = genesis

    # add some rewards
    reward.mint(alice, 10 * UNIT, sender=alice)
    reward.approve(distributor, 10 * UNIT, sender=alice)
    for i in range(10):
        distributor.deposit(i, UNIT, sender=alice)

    ve_distributor.migrate(sender=alice)
    ve_distributor.migrate(sender=bob)
    slope = DUST // 104
    slope2 = 2 * DUST // 104

    epoch1_rewards = UNIT * (DUST + 8 * slope) // (4 * DUST + 8 * slope + 8 * slope2)
    epoch2_rewards = UNIT * (DUST + 7 * slope) // (4 * DUST + 7 * slope + 7 * slope2)

    # fast forward to middle of epoch 1
    chain.pending_timestamp = genesis + EPOCH_LENGTH * 3 // 2

    # user claims rewards
    assert ve_distributor.claim(alice, sender=bob).return_value == epoch1_rewards // 2

    # simulate early exit
    veyfi.set_locked(alice, 0, 0, sender=deployer)

    # when reporting, all rewards until the end of the epoch will be reclaimed
    chain.pending_timestamp = genesis + EPOCH_LENGTH * 5 // 2
    reclaimed = ve_distributor.report(alice, sender=charlie).return_value[0]
    assert reclaimed == epoch1_rewards // 2 + epoch2_rewards
    assert reward.balanceOf(deployer) == reclaimed

def test_report_false(chain, deployer, alice, bob, charlie, reward, distributor, genesis, veyfi, snapshot, ve_distributor):
    # cannot report a false early exit
    unlock = genesis + 4 * EPOCH_LENGTH
    snapshot.set_snapshot(alice, DUST, 8, unlock, sender=deployer)
    snapshot.set_snapshot(bob, 2 * DUST, 8, unlock, sender=deployer)
    veyfi.set_locked(alice, DUST, unlock, sender=deployer)
    veyfi.set_locked(bob, 2 * DUST, unlock, sender=deployer)

    chain.pending_timestamp = genesis

    # add some rewards
    reward.mint(alice, 10 * UNIT, sender=alice)
    reward.approve(distributor, 10 * UNIT, sender=alice)
    for i in range(10):
        distributor.deposit(i, UNIT, sender=alice)

    ve_distributor.migrate(sender=alice)
    ve_distributor.migrate(sender=bob)

    chain.pending_timestamp = genesis + EPOCH_LENGTH * 3 // 2
    chain.mine()

    with reverts():
        ve_distributor.report(alice, sender=charlie)

    veyfi.set_locked(alice, 0, 0, sender=deployer)
    ve_distributor.report(alice, sender=charlie)
