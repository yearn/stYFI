from ape import reverts
from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
COMPONENTS_SENTINEL = '0x1111111111111111111111111111111111111111'
UNIT = 10**18
PRECISION = 10**30
DUST = 10**12

@fixture
def styfi_distributor(project, deployer, reward, styfi, distributor):
    srd = project.StakingRewardDistributor.deploy(distributor, reward, sender=deployer)
    srd.set_depositor(styfi, sender=deployer)
    srd.set_staking(styfi, sender=deployer)
    styfi.set_hooks(srd, sender=deployer)
    distributor.add_component(srd, 4, 1, COMPONENTS_SENTINEL, sender=deployer)

    return srd

@fixture
def claimer(project, deployer, reward, styfi_distributor):
    claimer = project.RewardClaimer.deploy(reward, sender=deployer)
    claimer.add_component(styfi_distributor, sender=deployer)
    styfi_distributor.set_claimer(claimer, True, sender=deployer)
    return claimer

def test_stake(chain, alice, yfi, styfi, styfi_distributor):
    yfi.mint(alice, 4 * UNIT, sender=alice)
    yfi.approve(styfi, 4 * UNIT, sender=alice)

    # cant deposit before genesis time
    with reverts():
        styfi.deposit(UNIT, sender=alice)

    # initial deposit
    assert styfi_distributor.total_weight_entries(0).weight == DUST
    chain.pending_timestamp = styfi_distributor.genesis()
    styfi.deposit(UNIT, sender=alice)
    assert styfi_distributor.total_weight_cursor().count == 1
    assert styfi_distributor.total_weight_entries(0) == [0, DUST + UNIT]

    # another deposit in same epoch
    styfi.deposit(2 * UNIT, sender=alice)
    assert styfi_distributor.total_weight_cursor().count == 1
    assert styfi_distributor.total_weight_entries(0) == [0, DUST + 3 * UNIT]

    # deposit in the next epoch
    chain.pending_timestamp += EPOCH_LENGTH
    styfi.deposit(UNIT, sender=alice)
    assert styfi_distributor.total_weight_cursor().count == 2
    assert styfi_distributor.total_weight_entries(0) == (0, DUST + 3 * UNIT)
    assert styfi_distributor.total_weight_entries(1) == (1, DUST + 4 * UNIT)

def test_unstake(chain, alice, yfi, styfi, styfi_distributor):
    yfi.mint(alice, 3 * UNIT, sender=alice)
    yfi.approve(styfi, 3 * UNIT, sender=alice)

    chain.pending_timestamp = styfi_distributor.genesis()
    styfi.deposit(3 * UNIT, sender=alice)

    # unstake
    styfi.unstake(2 * UNIT, sender=alice)

    assert styfi_distributor.total_weight_cursor().count == 1
    assert styfi_distributor.total_weight_entries(0) == (0, DUST + UNIT)

    # unstake more next epoch
    chain.pending_timestamp += EPOCH_LENGTH
    styfi.unstake(UNIT, sender=alice)
    assert styfi_distributor.total_weight_cursor().count == 2
    assert styfi_distributor.total_weight_entries(0) == (0, DUST + UNIT)
    assert styfi_distributor.total_weight_entries(1) == (1, DUST)

def test_transfer(chain, alice, bob, yfi, styfi, styfi_distributor):
    yfi.mint(alice, 3 * UNIT, sender=alice)
    yfi.approve(styfi, 3 * UNIT, sender=alice)

    chain.pending_timestamp = styfi_distributor.genesis()
    styfi.deposit(3 * UNIT, sender=alice)

    # unstake
    styfi.transfer(bob, 2 * UNIT, sender=alice)

    assert styfi_distributor.total_weight_cursor().count == 1
    assert styfi_distributor.total_weight_entries(0) == (0, DUST + 3 * UNIT)

    # transfer more next epoch
    chain.pending_timestamp += EPOCH_LENGTH
    styfi.transfer(bob, UNIT, sender=alice)
    assert styfi_distributor.total_weight_cursor().count == 1
    assert styfi_distributor.total_weight_entries(0) == (0, DUST + 3 * UNIT)

def test_rewards(chain, deployer, alice, bob, charlie, reward, yfi, styfi, distributor, genesis, styfi_distributor, claimer):
    styfi_distributor.set_claimer(alice, True, sender=deployer)

    # deposit small amount to test precision and make it easier to check math
    yfi.mint(alice, 3 * DUST, sender=alice)
    yfi.approve(styfi, 3 * DUST, sender=alice)

    chain.pending_timestamp = genesis
    styfi.deposit(DUST, sender=alice)

    # add some rewards
    reward.mint(alice, UNIT, sender=alice)
    reward.approve(distributor, UNIT, sender=alice)
    distributor.deposit(0, UNIT, sender=alice)

    # fast forward to middle of epoch and stake some more
    assert distributor.epoch_total_weight(0) == 0
    assert distributor.epoch_weights(styfi_distributor, 0) == 0
    assert styfi_distributor.epoch_rewards() == (0, 0)
    assert styfi_distributor.pending_rewards(alice) == 0

    ts = genesis + EPOCH_LENGTH * 3 // 2
    chain.pending_timestamp = ts
    styfi.deposit(DUST, sender=alice)
    chain.pending_timestamp = ts
    styfi.deposit(DUST, bob, sender=alice)

    assert distributor.epoch_total_weight(0) == 4 * 2 * DUST
    assert distributor.epoch_weights(styfi_distributor, 0) == 4 * 2 * DUST
    assert styfi_distributor.epoch_rewards() == (ts - genesis, UNIT)
    integral = UNIT // 2 * PRECISION // (2 * DUST)
    assert styfi_distributor.reward_integral() == integral
    assert styfi_distributor.account_reward_integral(alice) == integral
    assert styfi_distributor.pending_rewards(alice) == UNIT // 4

    # fast forward to end of epoch
    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts
    styfi_distributor.sync_rewards(alice, sender=alice)
    chain.pending_timestamp = ts
    styfi_distributor.sync_rewards(bob, sender=alice)
    
    integral += UNIT // 2 * PRECISION // (4 * DUST)
    assert styfi_distributor.reward_integral() == integral
    assert styfi_distributor.account_reward_integral(alice) == integral
    assert styfi_distributor.pending_rewards(alice) == UNIT // 2
    assert styfi_distributor.account_reward_integral(bob) == integral
    assert styfi_distributor.pending_rewards(bob) == UNIT // 8

    with chain.isolate():
        # rewards can be claimed through the RewardClaimer
        chain.pending_timestamp = ts
        assert claimer.claim(charlie, sender=alice).return_value == UNIT // 2
        assert reward.balanceOf(charlie) == UNIT // 2

    chain.pending_timestamp = ts
    styfi_distributor.claim(alice, sender=alice)
    assert styfi_distributor.pending_rewards(alice) == 0
    assert reward.balanceOf(alice) == UNIT // 2

def test_reclaim(chain, deployer, alice, bob, reward, yfi, styfi, distributor, genesis, styfi_distributor):
    # deposit small amount to test precision and make it easier to check math
    yfi.mint(alice, 3 * DUST, sender=alice)
    yfi.approve(styfi, 3 * DUST, sender=alice)

    chain.pending_timestamp = genesis
    styfi.deposit(DUST, sender=alice)
    styfi.deposit(2 * DUST, bob, sender=alice)

    styfi_distributor.set_reward_expiration(3, 0, deployer, sender=deployer)

    # add some rewards
    reward.mint(alice, 1000 * UNIT, sender=alice)
    reward.approve(distributor, 2**256 - 1, sender=alice)
    for i in range(6):
        distributor.deposit(i, (i + 1) * UNIT, sender=alice)

    # no rewards yet in epoch 0, nothing to reclaim
    with chain.isolate():
        chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
        # on beginning of epoch 3, we can reclaim rewards from end of epoch 3-3=0
        # but rewards only start in epoch 1
        reclaimed = styfi_distributor.reclaim(alice, sender=bob).return_value[0]
        assert reclaimed == 0
        assert reward.balanceOf(deployer) == 0

    # upate multiple epochs at once
    with chain.isolate():
        chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
        # on beginning of epoch 4, we can reclaim rewards from end of epoch 4-3=1
        styfi_distributor.account_reward_integral(alice) == 0
        reclaimed = styfi_distributor.reclaim(alice, sender=bob).return_value[0]
        assert reclaimed == UNIT // 4
        assert reward.balanceOf(deployer) == UNIT // 4
        styfi_distributor.account_reward_integral(alice) == styfi_distributor.reward_integral_snapshot(1)

    # update only a single epoch
    with chain.isolate():
        chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
        styfi_distributor.sync_rewards(sender=deployer)
        chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
        # on beginning of epoch 4, we can reclaim rewards from end of epoch 4-3=1
        reclaimed = styfi_distributor.reclaim(alice, sender=bob).return_value[0]
        assert reclaimed == UNIT // 4
        assert reward.balanceOf(deployer) == UNIT // 4

    # try middle of epoch 5
    with chain.isolate():
        chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH + EPOCH_LENGTH // 2
        # in middle of epoch 5, we can still only reclaim rewards until end of epoch 1
        reclaimed = styfi_distributor.reclaim(alice, sender=bob).return_value[0]
        assert reclaimed == UNIT // 4
        assert reward.balanceOf(deployer) == UNIT // 4

    with chain.isolate():
        chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH
        # in epoch 6, we can reclaim rewards until end of epoch 2
        reclaimed = styfi_distributor.reclaim(alice, sender=bob).return_value[0]
        assert reclaimed == UNIT // 4 + UNIT // 2
        assert reward.balanceOf(deployer) == UNIT // 4 + UNIT // 2

    # claim in middle of epoch 1, followed by reclaim in epoch 6
    with chain.isolate():
        styfi_distributor.set_claimer(bob, True, sender=deployer)
        chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH // 2
        styfi_distributor.claim(alice, sender=bob)
        assert reward.balanceOf(bob) == UNIT // 8
        chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH
        # in epoch 6, we can reclaim rewards until end of epoch 2
        reclaimed = styfi_distributor.reclaim(alice, sender=bob).return_value[0]
        assert reclaimed == UNIT // 4 + UNIT // 2 - UNIT // 8
        assert reward.balanceOf(deployer) == UNIT // 4 + UNIT // 2 - UNIT // 8

def test_reclaim_bounty(chain, deployer, alice, bob, reward, yfi, styfi, distributor, genesis, styfi_distributor):
    yfi.mint(alice, 3 * DUST, sender=alice)
    yfi.approve(styfi, 3 * DUST, sender=alice)

    chain.pending_timestamp = genesis
    styfi.deposit(DUST, sender=alice)
    styfi.deposit(2 * DUST, bob, sender=alice)

    styfi_distributor.set_reward_expiration(3, 1000, deployer, sender=deployer) # 10% bounty

    reward.mint(alice, UNIT, sender=alice)
    reward.approve(distributor, UNIT, sender=alice)
    distributor.deposit(0, UNIT, sender=alice)

    chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
    reclaimed, bounty = styfi_distributor.reclaim(alice, sender=bob).return_value

    expect_reclaim = UNIT // 4
    expect_bounty = expect_reclaim // 10
    expect_reclaim -= expect_bounty
    assert reclaimed == expect_reclaim
    assert reward.balanceOf(deployer) == expect_reclaim
    assert bounty == expect_bounty
    assert reward.balanceOf(bob) == expect_bounty

def test_total_weight(chain, deployer, alice, bob, yfi, styfi, distributor, genesis, styfi_distributor):
    distributor.set_component_scale(styfi_distributor, 1, 1, sender=deployer)

    yfi.mint(alice, 3 * DUST, sender=alice)
    yfi.approve(styfi, 3 * DUST, sender=alice)

    chain.pending_timestamp = genesis
    styfi.deposit(DUST, sender=alice)

    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH
    styfi.deposit(2 * DUST, bob, sender=alice)

    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    styfi_distributor.sync_rewards(sender=deployer)

    assert distributor.epoch_weights(styfi_distributor, 0) == 2 * DUST
    assert distributor.epoch_weights(styfi_distributor, 1) == 2 * DUST
    assert distributor.epoch_weights(styfi_distributor, 2) == 4 * DUST
