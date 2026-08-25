from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
COMPONENTS_SENTINEL = '0x1111111111111111111111111111111111111111'
UNIT = 10**18

@fixture
def styfi_distributor(project, deployer, reward, distributor):
    srd = project.StakingRewardDistributor.deploy(distributor, reward, sender=deployer)
    distributor.add_component(srd, 4, 1, COMPONENTS_SENTINEL, sender=deployer)
    return srd

@fixture
def aggregator(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def staking_middleware(project, deployer, styfi, styfi_distributor, aggregator):
    middleware = project.StakingMiddleware.deploy(styfi, styfi_distributor, aggregator, sender=deployer)
    styfi.set_hooks(middleware, sender=deployer)
    styfi_distributor.set_depositor(middleware, sender=deployer)
    styfi_distributor.set_staking(styfi, sender=deployer)
    return middleware

@fixture
def delegated(chain, project, deployer, genesis, styfi, staking_middleware):
    delegated = project.DelegatedStakedYFI.deploy(styfi, sender=deployer)
    staking_middleware.set_instant_withdrawal(delegated, True, sender=deployer)
    chain.pending_timestamp = genesis
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

def test_midleware(chain, project, deployer, alice, bob, genesis, yfi, delegated, delegated_distributor):
    yfi.mint(alice, 3 * UNIT, sender=alice)
    yfi.approve(delegated, 3 * UNIT, sender=alice)
    delegated.deposit(UNIT, sender=alice)

    middleware = project.DelegatedStakingMiddleware.deploy(genesis, delegated, delegated_distributor, sender=deployer)
    assert middleware.packed_supply() == UNIT << 108 | UNIT
    assert middleware.weight() == UNIT

    delegated.set_hooks(middleware, sender=deployer)
    delegated_distributor.set_depositor(middleware, sender=deployer)

    delegated.deposit(2 * UNIT, sender=alice)
    assert middleware.packed_supply() == UNIT << 108 | (3 * UNIT)
    assert middleware.weight() == UNIT

    chain.pending_timestamp += EPOCH_LENGTH
    chain.mine()
    assert middleware.weight() == 3 * UNIT

    delegated.unstake(UNIT, sender=alice)
    assert middleware.packed_supply() == 1 << 216 | (3 * UNIT << 108) | (2 * UNIT)
    assert middleware.weight() == 3 * UNIT

    delegated.transfer(bob, UNIT, sender=alice)
    assert middleware.packed_supply() == 1 << 216 | (3 * UNIT << 108) | (2 * UNIT)
    assert middleware.weight() == 3 * UNIT

    chain.pending_timestamp += EPOCH_LENGTH
    chain.mine()
    assert middleware.weight() == 2 * UNIT
