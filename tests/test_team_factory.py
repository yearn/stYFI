from pytest import fixture

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

@fixture
def implementation(project, deployer):
    return project.Team.deploy(sender=deployer)

@fixture
def registry(chain, project, deployer, genesis):
    chain.pending_timestamp = genesis
    return project.TeamRegistry.deploy(genesis, sender=deployer)

@fixture
def factory(project, deployer, registry, implementation):
    factory = project.TeamFactory.deploy(registry, implementation, sender=deployer)
    registry.set_factory(factory, sender=deployer)
    return factory

def test_deploy(project, alice, bob, factory):
    assert factory.num_deployments() == 0
    assert factory.deployments(0) == ZERO_ADDRESS
    team = project.Team.at(factory.deploy("A", sender=alice).return_value)
    assert team.name() == "A"
    assert team.owner() == alice
    assert factory.num_deployments() == 1
    assert factory.deployments(0) == team
    assert factory.deployed(team)
    
    team2 = project.Team.at(factory.deploy("B", bob, sender=alice).return_value)
    assert team2.name() == "B"
    assert team2.owner() == bob
    assert factory.num_deployments() == 2
    assert factory.deployments(1) == team2
    assert factory.deployed(team2)
