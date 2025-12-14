from ape import reverts
from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
COMPONENTS_SENTINEL = '0x1111111111111111111111111111111111111111'
UNIT = 10**18
PRECISION = 10**30
DUST = 10**12

@fixture
def styfi_distributor(project, deployer, reward, distributor):
    srd = project.StakingRewardDistributor.deploy(distributor, reward, sender=deployer)
    distributor.add_component(srd, 4, 1, COMPONENTS_SENTINEL, sender=deployer)

    return srd

@fixture
def middleware(project, deployer, styfi, styfi_distributor):
    middleware = project.StakingMiddleware.deploy(styfi, styfi_distributor, sender=deployer)
    styfi.set_hooks(middleware, sender=deployer)
    styfi_distributor.set_depositor(middleware, sender=deployer)
    styfi_distributor.set_staking(styfi, sender=deployer)

    return middleware

@fixture
def delegated(project, deployer, styfi, middleware):
    delegated = project.DelegatedStakedYFI.deploy(styfi, sender=deployer)
    middleware.set_instant_withdrawal(delegated, True, sender=deployer)
    return delegated

@fixture
def delegated_distributor(project, deployer, reward, styfi_distributor, delegated):
    drd = project.DelegatedStakingRewardDistributor.deploy(styfi_distributor, reward, sender=deployer)
    drd.set_depositor(delegated, sender=deployer)
    drd.set_staking(delegated, sender=deployer)
    drd.set_distributor_claim(delegated, sender=deployer)
    delegated.set_hooks(drd, sender=deployer)
    styfi_distributor.set_claimer(drd, True, sender=deployer)

    return drd

@fixture
def claimer(project, deployer, reward, delegated_distributor):
    claimer = project.RewardClaimer.deploy(reward, sender=deployer)
    claimer.add_component(delegated_distributor, sender=deployer)
    delegated_distributor.set_claimer(claimer, True, sender=deployer)
    return claimer

def test_stake(chain, alice, yfi, styfi, delegated, delegated_distributor):
    yfi.mint(alice, 4 * UNIT, sender=alice)
    yfi.approve(delegated, 4 * UNIT, sender=alice)

    # cant deposit before genesis time
    with reverts():
        delegated.deposit(UNIT, sender=alice)

    assert yfi.balanceOf(styfi) == 0
    assert styfi.balanceOf(delegated) == 0

    # initial deposit
    chain.pending_timestamp = delegated_distributor.genesis()
    delegated.deposit(UNIT, sender=alice)

    assert yfi.balanceOf(styfi) == UNIT
    assert styfi.balanceOf(delegated) == UNIT

    # another deposit
    delegated.deposit(3 * UNIT, sender=alice)
    assert yfi.balanceOf(styfi) == 4 * UNIT
    assert styfi.balanceOf(delegated) == 4 * UNIT

def test_unstake(chain, alice, yfi, styfi, delegated, delegated_distributor):
    yfi.mint(alice, 4 * UNIT, sender=alice)
    yfi.approve(delegated, 4 * UNIT, sender=alice)

    chain.pending_timestamp = delegated_distributor.genesis()
    delegated.deposit(4 * UNIT, sender=alice)
    assert yfi.balanceOf(styfi) == 4 * UNIT
    assert styfi.balanceOf(delegated) == 4 * UNIT

    # unstake
    ts = chain.pending_timestamp
    chain.pending_timestamp = ts
    delegated.unstake(UNIT, sender=alice)
    assert yfi.balanceOf(styfi) == 3 * UNIT
    assert yfi.balanceOf(delegated) == UNIT
    assert styfi.balanceOf(delegated) == 3 * UNIT

    assert delegated.maxWithdraw(alice) == 0
    chain.pending_timestamp = ts + EPOCH_LENGTH // 2
    chain.mine()
    assert delegated.maxWithdraw(alice) == UNIT // 2
    
    with chain.isolate():
        chain.pending_timestamp = ts + EPOCH_LENGTH // 2
        delegated.withdraw(UNIT // 2, sender=alice)
        assert yfi.balanceOf(alice) == UNIT // 2
        assert delegated.maxWithdraw(alice) == 0

    chain.pending_timestamp = ts + 2 * EPOCH_LENGTH
    chain.mine()
    assert delegated.maxWithdraw(alice) == UNIT
    
    chain.pending_timestamp = ts + 2 * EPOCH_LENGTH
    delegated.withdraw(UNIT, sender=alice)
    assert yfi.balanceOf(alice) == UNIT
    assert delegated.maxWithdraw(alice) == 0

def test_rewards(chain, deployer, alice, bob, charlie, reward, yfi, distributor, genesis, styfi_distributor, delegated, delegated_distributor, claimer):
    delegated_distributor.set_claimer(deployer, True, sender=deployer)

    # deposit small amount to test precision and make it easier to check math
    yfi.mint(alice, 4 * DUST, sender=alice)
    yfi.approve(delegated, 4 * DUST, sender=alice)

    chain.pending_timestamp = genesis
    delegated.deposit(DUST, sender=alice)

    # add some rewards
    reward.mint(alice, UNIT, sender=alice)
    reward.approve(distributor, UNIT, sender=alice)
    distributor.deposit(0, UNIT, sender=alice)

    # fast forward to middle of epoch and stake some more
    assert distributor.epoch_total_weight(0) == 0
    assert distributor.epoch_weights(styfi_distributor, 0) == 0
    assert styfi_distributor.epoch_rewards() == (0, 0)

    ts = genesis + EPOCH_LENGTH * 3 // 2
    chain.pending_timestamp = ts
    delegated.deposit(DUST, sender=alice)
    chain.pending_timestamp = ts
    delegated.deposit(2 * DUST, bob, sender=alice)

    assert distributor.epoch_total_weight(0) == 4 * 2 * DUST
    assert distributor.epoch_weights(styfi_distributor, 0) == 4 * 2 * DUST
    assert styfi_distributor.epoch_rewards() == (ts - genesis, UNIT)
    integral = UNIT // 4 * PRECISION // DUST

    with chain.isolate():
        # rewards can be claimed through the RewardClaimer
        chain.pending_timestamp = ts
        assert claimer.claim(charlie, sender=alice).return_value == UNIT // 4
        assert reward.balanceOf(charlie) == UNIT // 4

    chain.pending_timestamp = ts
    rewards = delegated_distributor.claim(alice, sender=deployer).return_value
    assert delegated_distributor.reward_integral() == integral
    assert delegated_distributor.account_reward_integral(alice) == integral
    assert rewards == UNIT // 4

    # fast forward to end of epoch
    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH
    rewards = delegated_distributor.claim(alice, sender=deployer).return_value
    
    integral += UNIT * 2 // 5 * PRECISION // (4 * DUST)
    assert delegated_distributor.reward_integral() == integral
    assert delegated_distributor.account_reward_integral(alice) == integral
    assert rewards == UNIT // 5

    rewards = delegated_distributor.claim(bob, sender=deployer).return_value
    assert delegated_distributor.account_reward_integral(bob) == integral
    assert rewards == UNIT // 5
