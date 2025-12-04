from ape import reverts
from pytest import fixture

ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'
UNIT = 10**18

@fixture
def claimer(project, deployer, reward):
    return project.RewardClaimer.deploy(reward, sender=deployer)

@fixture
def components(project, deployer, reward):
    return [project.MockRewardClaimerComponent.deploy(reward, sender=deployer) for _ in range(3)]

def test_claim(deployer, alice, reward, claimer, components):
    # claim rewards from all underlying components at once
    for i in range(3):
        reward.mint(components[i], i * UNIT, sender=deployer)
        components[i].set_rewards(alice, i * UNIT, sender=deployer)
        assert components[i].rewards(alice) == i * UNIT
        claimer.add_component(components[i], sender=deployer)

    assert claimer.claim(sender=alice).return_value == 3 * UNIT
    assert reward.balanceOf(alice) == 3 * UNIT

    for i in range(3):
        assert components[i].rewards(alice) == 0

def test_claim_recipient(deployer, alice, bob, reward, claimer, components):
    # claim rewards from all underlying components at once and send to another address
    for i in range(3):
        reward.mint(components[i], i * UNIT, sender=deployer)
        components[i].set_rewards(alice, i * UNIT, sender=deployer)
        assert components[i].rewards(alice) == i * UNIT
        claimer.add_component(components[i], sender=deployer)

    assert claimer.claim(bob, sender=alice).return_value == 3 * UNIT
    assert reward.balanceOf(bob) == 3 * UNIT

    for i in range(3):
        assert components[i].rewards(alice) == 0

def test_add_component(deployer, claimer, components):
    # components can be added
    assert claimer.num_components() == 0
    assert claimer.components(0) == ZERO_ADDRESS
    claimer.add_component(components[0], sender=deployer)
    assert claimer.num_components() == 1
    assert claimer.components(0) == components[0]
    claimer.add_component(components[1], sender=deployer)
    assert claimer.num_components() == 2
    assert claimer.components(1) == components[1]

def test_add_component_permission(deployer, alice, claimer, components):
    # only management can add components
    with reverts():
        claimer.add_component(components[0], sender=alice)
    claimer.add_component(components[0], sender=deployer)

def test_replace_component(deployer, claimer, components):
    # components can be replaced
    claimer.add_component(components[0], sender=deployer)
    claimer.replace_component(0, components[1], sender=deployer)
    assert claimer.num_components() == 1
    assert claimer.components(0) == components[1]

def test_replace_component_permission(deployer, alice, claimer, components):
    # only management can replace components
    claimer.add_component(components[0], sender=deployer)
    with reverts():
        claimer.replace_component(0, components[1], sender=alice)
    claimer.replace_component(0, components[1], sender=deployer)

def test_remove_component(deployer, claimer, components):
    # components can be removed
    claimer.add_component(components[0], sender=deployer)
    claimer.add_component(components[1], sender=deployer)
    claimer.remove_component(sender=deployer)
    assert claimer.num_components() == 1
    assert claimer.components(0) == components[0]
    assert claimer.components(1) == ZERO_ADDRESS

def test_remove_component_permission(deployer, alice, claimer, components):
    # only management can replace components
    claimer.add_component(components[0], sender=deployer)
    with reverts():
        claimer.remove_component(sender=alice)
    claimer.remove_component(sender=deployer)
