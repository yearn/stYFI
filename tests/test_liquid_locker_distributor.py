from ape import reverts
from pytest import fixture, mark

EPOCH_LENGTH = 14 * 24 * 60 * 60
COMPONENTS_SENTINEL = '0x1111111111111111111111111111111111111111'
UNIT = 10**18
PRECISION = 10**30
DUST = 10**12
SCALES = [1, 4, 1]
SHARES = [UNIT, UNIT, 2 * UNIT]

@fixture
def ll_tokens(project, deployer):
    return [project.MockToken.deploy(sender=deployer) for _ in range(3)]

@fixture
def depositors(project, deployer, ll_tokens):
    return [project.LiquidLockerDepositor.deploy(ll_tokens[i], SCALES[i], f"{i}", f"{i}", sender=deployer) for i in range(3)]

@fixture
def ll_distributor(project, deployer, reward, distributor, genesis, depositors):
    llrd = project.LiquidLockerRewardDistributor.deploy(genesis, reward, 104, depositors, sender=deployer)
    llrd.set_distributor(distributor, sender=deployer)
    llrd.set_unboosted_weights(SHARES, sender=deployer)
    
    for depositor in depositors:
        depositor.set_hooks(llrd, sender=deployer)

    distributor.add_component(llrd, COMPONENTS_SENTINEL, sender=deployer)
    return llrd

@mark.parametrize("idx", [0, 1, 2])
def test_deposit(chain, alice, ll_tokens, depositors, ll_distributor, idx):
    token = ll_tokens[idx]
    depositor = depositors[idx]
    unit = SCALES[idx] * UNIT
    token.mint(alice, 4 * unit, sender=alice)
    token.approve(depositor, 4 * unit, sender=alice)

    # cant deposit before genesis time
    with reverts():
        depositor.deposit(unit, sender=alice)

    # initial deposit
    assert ll_distributor.staked(idx, alice).amount == 0
    assert ll_distributor.previous_staked(idx, alice).amount == 0
    assert ll_distributor.total_staked(idx).amount == DUST

    chain.pending_timestamp = ll_distributor.genesis()
    depositor.deposit(unit, sender=alice)

    assert ll_distributor.staked(idx, alice).amount == UNIT
    assert ll_distributor.previous_staked(idx, alice).amount == 0
    assert ll_distributor.total_staked(idx).amount == DUST + UNIT

    # another deposit in same epoch
    depositor.deposit(2 * unit, sender=alice)
    assert ll_distributor.staked(idx, alice).amount == 3 * UNIT
    assert ll_distributor.previous_staked(idx, alice).amount == 0
    assert ll_distributor.total_staked(idx).amount == DUST + 3 * UNIT

    # deposit in the next epoch
    chain.pending_timestamp += EPOCH_LENGTH
    depositor.deposit(unit, sender=alice)
    assert ll_distributor.staked(idx, alice).amount == 4 * UNIT
    assert ll_distributor.previous_staked(idx, alice).amount == 3 * UNIT
    assert ll_distributor.total_staked(idx).amount == DUST + 4 * UNIT
    assert ll_distributor.previous_total_staked(idx).amount == DUST + 3 * UNIT

@mark.parametrize("idx", [0, 1, 2])
def test_rewards(chain, alice, bob, reward, distributor, genesis, ll_tokens, depositors, ll_distributor, idx):
    token = ll_tokens[idx]
    depositor = depositors[idx]
    dust = SCALES[idx] * DUST

    # deposit small amount to test precision and make it easier to check math
    token.mint(alice, 3 * dust, sender=alice)
    token.approve(depositor, 3 * dust, sender=alice)

    chain.pending_timestamp = genesis
    depositor.deposit(dust, sender=alice)

    # add some rewards
    reward.mint(alice, UNIT, sender=alice)
    reward.approve(distributor, UNIT, sender=alice)
    distributor.deposit(0, UNIT, sender=alice)

    # fast forward to middle of epoch and stake some more
    assert distributor.epoch_total_weight(0) == 0
    assert distributor.epoch_weights(ll_distributor, 0) == 0
    assert ll_distributor.current_rewards(idx) == (0, 0)
    assert ll_distributor.pending_rewards(alice) == 0

    ts = genesis + EPOCH_LENGTH * 3 // 2
    chain.pending_timestamp = ts
    depositor.deposit(dust, sender=alice)
    depositor.deposit(dust, bob, sender=alice)
    
    epoch_rewards = UNIT * SHARES[idx] // sum(SHARES)

    assert distributor.epoch_total_weight(0) == sum(SHARES) * 2 # boost
    assert distributor.epoch_weights(ll_distributor, 0) == sum(SHARES) * 2 # boost
    assert ll_distributor.current_rewards(idx) == (ts - genesis, epoch_rewards)
    integral = epoch_rewards // 2 * PRECISION // (2 * DUST)
    assert ll_distributor.reward_integral(idx) == integral
    assert ll_distributor.account_reward_integral(idx, alice) == integral
    assert ll_distributor.pending_rewards(alice) == epoch_rewards // 4

    # fast forward to end of epoch
    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH
    ll_distributor.sync_rewards(idx, alice, sender=alice)
    ll_distributor.sync_rewards(idx, bob, sender=alice)
    
    integral += epoch_rewards // 2 * PRECISION // (4 * DUST)
    assert ll_distributor.reward_integral(idx) == integral
    assert ll_distributor.account_reward_integral(idx, alice) == integral
    assert ll_distributor.pending_rewards(alice) == epoch_rewards // 2
    assert ll_distributor.account_reward_integral(idx, bob) == integral
    assert ll_distributor.pending_rewards(bob) == epoch_rewards // 8
