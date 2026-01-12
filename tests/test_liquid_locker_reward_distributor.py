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
def ll_distributor(project, deployer, reward, distributor, depositors):
    llrd = project.LiquidLockerRewardDistributor.deploy(distributor, reward, 104, depositors, sender=deployer)
    llrd.set_unboosted_weights(SHARES, sender=deployer)
    
    for depositor in depositors:
        depositor.set_capacity(10 * UNIT, sender=deployer)
        depositor.set_hooks(llrd, sender=deployer)

    distributor.add_component(llrd, 4, 1, COMPONENTS_SENTINEL, sender=deployer)
    return llrd

@fixture
def claimer(project, deployer, reward, ll_distributor):
    claimer = project.RewardClaimer.deploy(reward, sender=deployer)
    claimer.add_component(ll_distributor, sender=deployer)
    ll_distributor.set_claimer(claimer, True, sender=deployer)
    return claimer

@mark.parametrize("idx", [0, 1, 2])
def test_rewards(chain, alice, bob, charlie, reward, distributor, genesis, ll_tokens, depositors, ll_distributor, claimer, idx):
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
    chain.pending_timestamp = ts
    depositor.deposit(dust, bob, sender=alice)
    
    epoch_rewards = UNIT * SHARES[idx] // sum(SHARES)

    assert distributor.epoch_total_weight(0) == 4 * sum(SHARES) * 2 # boost
    assert distributor.epoch_weights(ll_distributor, 0) == 4 * sum(SHARES) * 2 # boost
    assert ll_distributor.current_rewards(idx) == (ts - genesis, epoch_rewards)
    integral = epoch_rewards // 2 * PRECISION // (2 * DUST)
    assert ll_distributor.reward_integral(idx) == integral
    assert ll_distributor.account_reward_integral(idx, alice) == integral
    assert ll_distributor.pending_rewards(alice) == epoch_rewards // 4

    with chain.isolate():
        # rewards can be claimed through the RewardClaimer
        chain.pending_timestamp = ts
        assert claimer.claim(charlie, sender=alice).return_value == epoch_rewards // 4
        assert reward.balanceOf(charlie) == epoch_rewards // 4

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

@mark.parametrize("idx", [0, 1, 2])
def test_reclaim(chain, deployer, alice, bob, reward, distributor, genesis, ll_tokens, depositors, ll_distributor, idx):
    token = ll_tokens[idx]
    depositor = depositors[idx]
    dust = SCALES[idx] * DUST

    # deposit small amount to test precision and make it easier to check math
    token.mint(alice, 3 * dust, sender=alice)
    token.approve(depositor, 3 * dust, sender=alice)

    chain.pending_timestamp = genesis
    depositor.deposit(dust, sender=alice)
    depositor.deposit(2 * dust, bob, sender=alice)

    ll_distributor.set_reward_expiration(3, 0, deployer, sender=deployer)

    # add some rewards
    reward.mint(alice, 1000 * UNIT, sender=alice)
    reward.approve(distributor, 2**256 - 1, sender=alice)
    for i in range(6):
        distributor.deposit(i, (i + 1) * UNIT, sender=alice)
    epoch_rewards = UNIT * SHARES[idx] // sum(SHARES)

    # no rewards yet in epoch 0, nothing to reclaim
    with chain.isolate():
        chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
        # on beginning of epoch 3, we can reclaim rewards from end of epoch 3-3=0
        # but rewards only start in epoch 1
        reclaimed = ll_distributor.reclaim(idx, alice, sender=bob).return_value[0]
        assert reclaimed == 0
        assert reward.balanceOf(deployer) == 0

    # upate multiple epochs at once
    with chain.isolate():
        chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
        # on beginning of epoch 4, we can reclaim rewards from end of epoch 4-3=1
        ll_distributor.account_reward_integral(idx, alice) == 0
        reclaimed = ll_distributor.reclaim(idx, alice, sender=bob).return_value[0]
        assert reclaimed == epoch_rewards // 4
        assert reward.balanceOf(deployer) == epoch_rewards // 4
        assert ll_distributor.account_reward_integral(idx, alice) == ll_distributor.reward_integral_snapshot(idx, 1)

    # update only a single epoch
    with chain.isolate():
        chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
        ll_distributor.sync_rewards(idx, sender=deployer)
        chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
        # on beginning of epoch 4, we can reclaim rewards from end of epoch 4-3=1
        reclaimed = ll_distributor.reclaim(idx, alice, sender=bob).return_value[0]
        assert reclaimed == epoch_rewards // 4
        assert reward.balanceOf(deployer) == epoch_rewards // 4

    # try middle of epoch 4
    with chain.isolate():
        chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH + EPOCH_LENGTH // 2
        # in middle of epoch 4, we can still only reclaim rewards until end of epoch 1
        reclaimed = ll_distributor.reclaim(idx, alice, sender=bob).return_value[0]
        assert reclaimed == epoch_rewards // 4
        assert reward.balanceOf(deployer) == epoch_rewards // 4

    with chain.isolate():
        chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH
        # in epoch 5, we can reclaim rewards until end of epoch 2
        reclaimed = ll_distributor.reclaim(idx, alice, sender=bob).return_value[0]
        assert reclaimed == epoch_rewards // 4 + epoch_rewards // 2
        assert reward.balanceOf(deployer) == epoch_rewards // 4 + epoch_rewards // 2

    # claim in middle of epoch 1, followed by reclaim in epoch 5
    with chain.isolate():
        ll_distributor.set_claimer(bob, True, sender=deployer)
        chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH // 2
        ll_distributor.claim(alice, sender=bob)
        assert reward.balanceOf(bob) == epoch_rewards // 8
        chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH
        # in epoch 5, we can reclaim rewards until end of epoch 2
        reclaimed = ll_distributor.reclaim(idx, alice, sender=bob).return_value[0]
        assert reclaimed == epoch_rewards // 4 + epoch_rewards // 2 - epoch_rewards // 8
        assert reward.balanceOf(deployer) == epoch_rewards // 4 + epoch_rewards // 2 - epoch_rewards // 8

@mark.parametrize("idx", [0, 1, 2])
def test_reclaim_accrued(chain, deployer, alice, bob, reward, distributor, genesis, ll_tokens, depositors, ll_distributor, idx):
    token = ll_tokens[idx]
    depositor = depositors[idx]
    dust = SCALES[idx] * DUST

    # deposit small amount to test precision and make it easier to check math
    token.mint(alice, 3 * dust, sender=alice)
    token.approve(depositor, 3 * dust, sender=alice)

    chain.pending_timestamp = genesis
    depositor.deposit(dust, sender=alice)
    depositor.deposit(2 * dust, bob, sender=alice)

    ll_distributor.set_reward_expiration(3, 0, deployer, sender=deployer)

    # add some rewards
    reward.mint(alice, 1000 * UNIT, sender=alice)
    reward.approve(distributor, 2**256 - 1, sender=alice)
    for i in range(6):
        distributor.deposit(i, (i + 1) * UNIT, sender=alice)
    epoch_rewards = UNIT * SHARES[idx] // sum(SHARES)

    # sync in middle of epoch 1
    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH // 2
    ll_distributor.sync_rewards(idx, alice, sender=bob)
    assert ll_distributor.pending_rewards(alice) == epoch_rewards // 8
    assert ll_distributor.accrued_rewards(alice) == (2, 0)

    # claim in middle of epoch 1, followed by reclaim in epoch 5
    # in epoch 5, we can reclaim rewards until end of epoch 2
    with chain.isolate():
        # without reclaiming accrued
        chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH
        reclaimed = ll_distributor.reclaim(idx, alice, sender=bob).return_value[0]
        assert reclaimed == epoch_rewards // 8 + epoch_rewards // 2

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH
    reclaimed = ll_distributor.reclaim(idx, alice, 1, sender=bob).return_value[0]
    assert reclaimed == epoch_rewards // 4 + epoch_rewards // 2
    assert reward.balanceOf(deployer) == epoch_rewards // 4 + epoch_rewards // 2

def test_sweep(project, deployer, ll_distributor):
    # tokens can be transfered out
    token = project.MockToken.deploy(sender=deployer)
    token.mint(ll_distributor, 3 * UNIT, sender=deployer)
    assert token.balanceOf(deployer) == 0
    assert token.balanceOf(ll_distributor) == 3 * UNIT
    ll_distributor.sweep(token, UNIT, sender=deployer)
    assert token.balanceOf(deployer) == UNIT
    assert token.balanceOf(ll_distributor) == 2 * UNIT
    ll_distributor.sweep(token, sender=deployer)
    assert token.balanceOf(deployer) == 3 * UNIT
    assert token.balanceOf(ll_distributor) == 0

def test_sweep_permission(project, deployer, alice, ll_distributor):
    # only management can transfer tokens out
    token = project.MockToken.deploy(sender=deployer)
    token.mint(ll_distributor, UNIT, sender=deployer)
    with reverts():
        ll_distributor.sweep(token, sender=alice)
    ll_distributor.sweep(token, sender=deployer)
