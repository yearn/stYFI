from ape import reverts
from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
COMPONENTS_SENTINEL = '0x1111111111111111111111111111111111111111'
ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'
UNIT = 10**18

@fixture
def components(project, deployer, distributor):
    return [project.MockRewardDistributorComponent.deploy(distributor, sender=deployer) for _ in range(3)]

def test_deposit(chain, alice, reward, distributor, genesis):
    # rewards can be scheduled for the current or a future epoch
    reward.mint(alice, 3 * UNIT, sender=alice)
    reward.approve(distributor, 3 * UNIT, sender=alice)

    assert distributor.epoch_rewards(0) == 0
    assert reward.balanceOf(distributor) == 0

    chain.pending_timestamp = genesis + EPOCH_LENGTH // 2
    distributor.deposit(0, UNIT, sender=alice)

    assert distributor.epoch_rewards(0) == UNIT
    assert reward.balanceOf(distributor) == UNIT

    distributor.deposit(1, 2 * UNIT, sender=alice)
    assert distributor.epoch_rewards(1) == 2 * UNIT
    assert reward.balanceOf(distributor) == 3 * UNIT

def test_deposit_past(chain, alice, reward, distributor, genesis):
    # rewards cant be added to a past epoch
    reward.mint(alice, UNIT, sender=alice)
    reward.approve(distributor, UNIT, sender=alice)

    chain.pending_timestamp = genesis + EPOCH_LENGTH * 3 // 2
    with reverts():
        distributor.deposit(0, UNIT, sender=alice)
    distributor.deposit(1, UNIT, sender=alice)

def test_sync(chain, deployer, reward, distributor, genesis, components):
    for i in range(3):
        distributor.add_component(components[i], i + 1, 1, COMPONENTS_SENTINEL, sender=deployer)

    components[0].set_total_weight(0, 3, sender=deployer)
    components[1].set_total_weight(0, 2, sender=deployer)
    components[2].set_total_weight(0, 1, sender=deployer)

    reward.mint(deployer, UNIT, sender=deployer)
    reward.approve(distributor, UNIT, sender=deployer)

    chain.pending_timestamp = genesis
    distributor.deposit(0, UNIT, sender=deployer)
    assert distributor.sync(sender=deployer).return_value
    assert distributor.last_epoch() == 0

    chain.pending_timestamp = genesis + EPOCH_LENGTH
    assert distributor.sync(sender=deployer).return_value
    assert distributor.last_epoch() == 1
    assert distributor.epoch_total_weight(0) == 10
    assert distributor.epoch_weights(components[0], 0) == 3
    assert distributor.epoch_weights(components[1], 0) == 4
    assert distributor.epoch_weights(components[2], 0) == 3

    assert components[1].claim_upstream(sender=deployer).return_value == (0, 4, UNIT * 4 // 10)

def test_claim(chain, deployer, reward, distributor, genesis, components):
    for i in range(3):
        distributor.add_component(components[i], i + 1, 1, COMPONENTS_SENTINEL, sender=deployer)

    components[0].set_total_weight(0, 3, sender=deployer)
    components[1].set_total_weight(0, 2, sender=deployer)
    components[2].set_total_weight(0, 1, sender=deployer)

    reward.mint(deployer, UNIT, sender=deployer)
    reward.approve(distributor, UNIT, sender=deployer)

    chain.pending_timestamp = genesis
    distributor.deposit(0, UNIT, sender=deployer)

    chain.pending_timestamp = genesis + EPOCH_LENGTH
    assert components[1].claim_upstream(sender=deployer).return_value == (0, 4, UNIT * 4 // 10)

    with reverts():
        assert components[1].claim_upstream(sender=deployer).return_value == (0, 4, UNIT * 4 // 10)

def test_pull(project, chain, deployer, reward, distributor, genesis, components):
    for i in range(3):
        distributor.add_component(components[i], i + 1, 1, COMPONENTS_SENTINEL, sender=deployer)
    
    pull = project.MockPull.deploy(distributor, reward, sender=deployer)
    pull.set_rewards(0, 2 * UNIT, sender=deployer)
    distributor.set_pull(pull, sender=deployer)

    components[0].set_total_weight(0, 3, sender=deployer)
    components[1].set_total_weight(0, 2, sender=deployer)
    components[2].set_total_weight(0, 1, sender=deployer)

    reward.mint(deployer, UNIT, sender=deployer)
    reward.mint(pull, 2 * UNIT, sender=deployer)
    reward.approve(distributor, UNIT, sender=deployer)

    chain.pending_timestamp = genesis
    distributor.deposit(0, UNIT, sender=deployer)
    
    chain.pending_timestamp = genesis + EPOCH_LENGTH
    assert distributor.sync(sender=deployer).return_value
    assert reward.balanceOf(distributor) == 3 * UNIT
    assert distributor.epoch_rewards(0) == 3 * UNIT

def test_add_component(deployer, distributor, components):
    assert distributor.num_components() == 0
    assert distributor.components(COMPONENTS_SENTINEL) == (COMPONENTS_SENTINEL, 0, 0, 0)

    distributor.add_component(components[0], 2, 1, COMPONENTS_SENTINEL, sender=deployer)
    assert distributor.num_components() == 1
    assert distributor.components(COMPONENTS_SENTINEL) == (components[0], 0, 0, 0)
    assert distributor.components(components[0]) == (COMPONENTS_SENTINEL, 0, 2, 1)

    distributor.add_component(components[1], 3, 4, COMPONENTS_SENTINEL, sender=deployer)
    assert distributor.num_components() == 2
    assert distributor.components(COMPONENTS_SENTINEL) == (components[1], 0, 0, 0)
    assert distributor.components(components[1]) == (components[0], 0, 3, 4)
    assert distributor.components(components[0]) == (COMPONENTS_SENTINEL, 0, 2, 1)

    distributor.add_component(components[2], 5, 6, components[1], sender=deployer)
    assert distributor.num_components() == 3
    assert distributor.components(COMPONENTS_SENTINEL) == (components[1], 0, 0, 0)
    assert distributor.components(components[1]) == (components[2], 0, 3, 4)
    assert distributor.components(components[2]) == (components[0], 0, 5, 6)
    assert distributor.components(components[0]) == (COMPONENTS_SENTINEL, 0, 2, 1)

def test_add_component_later(chain, deployer, distributor, genesis, components):
    distributor.add_component(components[0], 3, 2, COMPONENTS_SENTINEL, sender=deployer)

    chain.pending_timestamp = genesis + EPOCH_LENGTH
    components[0].claim_upstream(sender=deployer)
    assert distributor.components(components[0]) == (COMPONENTS_SENTINEL, 1, 3, 2)

def test_set_component_scale(chain, deployer, distributor, genesis, components):
    distributor.add_component(components[0], 3, 2, COMPONENTS_SENTINEL, sender=deployer)

    chain.pending_timestamp = genesis + EPOCH_LENGTH
    components[0].claim_upstream(sender=deployer)
    distributor.set_component_scale(components[0], 4, 5, sender=deployer)
    assert distributor.components(components[0]) == (COMPONENTS_SENTINEL, 1, 4, 5)

def test_remove_component(chain, deployer, distributor, genesis, components):
    distributor.add_component(components[0], 3, 2, COMPONENTS_SENTINEL, sender=deployer)

    chain.pending_timestamp = genesis + EPOCH_LENGTH
    components[0].claim_upstream(sender=deployer)
    distributor.remove_component(components[0], COMPONENTS_SENTINEL, sender=deployer)
    assert distributor.components(components[0]) == (ZERO_ADDRESS, 1, 0, 0)
    assert distributor.components(COMPONENTS_SENTINEL) == (COMPONENTS_SENTINEL, 0, 0, 0)
    assert distributor.num_components() == 0

def test_readd_component(chain, deployer, distributor, genesis, components):
    distributor.add_component(components[0], 3, 2, COMPONENTS_SENTINEL, sender=deployer)

    chain.pending_timestamp = genesis + EPOCH_LENGTH
    components[0].claim_upstream(sender=deployer)
    distributor.remove_component(components[0], COMPONENTS_SENTINEL, sender=deployer)

    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH
    distributor.add_component(components[0], 3, 2, COMPONENTS_SENTINEL, sender=deployer)
    assert distributor.components(components[0]) == (COMPONENTS_SENTINEL, 1, 3, 2)
    assert distributor.components(COMPONENTS_SENTINEL) == (components[0], 0, 0, 0)
    assert distributor.num_components() == 1
