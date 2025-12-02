from ape import reverts
from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
COMPONENTS_SENTINEL = '0x1111111111111111111111111111111111111111'
UNIT = 10**18
PRECISION = 10**30
BIG_MASK = 2**112 - 1
DUST = 10**12

@fixture
def styfi_distributor(project, deployer, reward, styfi, distributor, genesis):
    srd = project.StakingRewardDistributor.deploy(genesis, reward, sender=deployer)
    srd.set_depositor(styfi, sender=deployer)
    srd.set_distributor(distributor, sender=deployer)
    styfi.set_hooks(srd, sender=deployer)
    distributor.add_component(srd, COMPONENTS_SENTINEL, sender=deployer)

    return srd

def test_stake(chain, alice, yfi, styfi, styfi_distributor):
    yfi.mint(alice, 4 * UNIT, sender=alice)
    yfi.approve(styfi, 4 * UNIT, sender=alice)

    # cant deposit before genesis time
    with reverts():
        styfi.deposit(UNIT, sender=alice)

    # initial deposit
    assert styfi_distributor.packed_weights(alice) == 0
    assert styfi_distributor.previous_packed_weights(alice) == 0
    assert styfi_distributor.total_weight_entries(0).weight == DUST

    chain.pending_timestamp = styfi_distributor.genesis()
    styfi.deposit(UNIT, sender=alice)

    assert styfi_distributor.packed_weights(alice) & BIG_MASK == UNIT
    assert styfi_distributor.previous_packed_weights(alice) == 0
    assert styfi_distributor.total_weight_cursor().count == 1
    assert styfi_distributor.total_weight_entries(0) == [0, DUST + UNIT]

    # another deposit in same epoch
    styfi.deposit(2 * UNIT, sender=alice)
    assert styfi_distributor.packed_weights(alice) & BIG_MASK == 3 * UNIT
    assert styfi_distributor.previous_packed_weights(alice) == 0
    assert styfi_distributor.total_weight_cursor().count == 1
    assert styfi_distributor.total_weight_entries(0) == [0, DUST + 3 * UNIT]

    # deposit in the next epoch
    chain.pending_timestamp += EPOCH_LENGTH
    styfi.deposit(UNIT, sender=alice)
    assert styfi_distributor.packed_weights(alice) & BIG_MASK == 4 * UNIT
    assert styfi_distributor.previous_packed_weights(alice) & BIG_MASK == 3 * UNIT
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

    assert styfi_distributor.packed_weights(alice) & BIG_MASK == UNIT
    assert styfi_distributor.previous_packed_weights(alice) == 0
    assert styfi_distributor.total_weight_cursor().count == 1
    assert styfi_distributor.total_weight_entries(0) == (0, DUST + UNIT)

    # unstake more next epoch
    chain.pending_timestamp += EPOCH_LENGTH
    styfi.unstake(UNIT, sender=alice)
    assert styfi_distributor.packed_weights(alice) & BIG_MASK == 0
    assert styfi_distributor.previous_packed_weights(alice) & BIG_MASK == UNIT
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

    assert styfi_distributor.packed_weights(alice) & BIG_MASK == UNIT
    assert styfi_distributor.previous_packed_weights(alice) == 0
    assert styfi_distributor.packed_weights(bob) & BIG_MASK == 2 * UNIT
    assert styfi_distributor.previous_packed_weights(bob) == 0
    assert styfi_distributor.total_weight_cursor().count == 1
    assert styfi_distributor.total_weight_entries(0) == (0, DUST + 3 * UNIT)

    # transfer more next epoch
    chain.pending_timestamp += EPOCH_LENGTH
    styfi.transfer(bob, UNIT, sender=alice)
    assert styfi_distributor.packed_weights(alice) & BIG_MASK == 0
    assert styfi_distributor.previous_packed_weights(alice) & BIG_MASK == UNIT
    assert styfi_distributor.packed_weights(bob) & BIG_MASK == 3 * UNIT
    assert styfi_distributor.previous_packed_weights(bob) & BIG_MASK == 2 * UNIT
    assert styfi_distributor.total_weight_cursor().count == 1
    assert styfi_distributor.total_weight_entries(0) == (0, DUST + 3 * UNIT)

def test_rewards(chain, alice, bob, reward, yfi, styfi, distributor, genesis, styfi_distributor):
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
    styfi.deposit(DUST, bob, sender=alice)

    assert distributor.epoch_total_weight(0) == 4 * 2 * DUST
    assert distributor.epoch_weights(styfi_distributor, 0) == 4 * 2 * DUST
    assert styfi_distributor.epoch_rewards() == (ts - genesis, UNIT)
    integral = UNIT // 2 * PRECISION // (2 * DUST)
    assert styfi_distributor.reward_integral() == integral
    assert styfi_distributor.account_reward_integral(alice) == integral
    assert styfi_distributor.pending_rewards(alice) == UNIT // 4

    # fast forward to end of epoch
    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH
    styfi_distributor.sync_rewards(alice, sender=alice)
    styfi_distributor.sync_rewards(bob, sender=alice)
    
    integral += UNIT // 2 * PRECISION // (4 * DUST)
    assert styfi_distributor.reward_integral() == integral
    assert styfi_distributor.account_reward_integral(alice) == integral
    assert styfi_distributor.pending_rewards(alice) == UNIT // 2
    assert styfi_distributor.account_reward_integral(bob) == integral
    assert styfi_distributor.pending_rewards(bob) == UNIT // 8
