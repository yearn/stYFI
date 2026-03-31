from ape import reverts
from pytest import fixture

MAX = 2**256 - 1
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
PERIOD_LENGTH = 6 * 14 * 24 * 60 * 60

@fixture
def registry(chain, project, deployer, genesis):
    chain.pending_timestamp = genesis
    return project.TeamRegistry.deploy(genesis, sender=deployer)

@fixture
def implementation(project, deployer):
    return project.Team.deploy(sender=deployer)

@fixture
def factory(project, deployer, registry, implementation):
    factory = project.TeamFactory.deploy(registry, implementation, sender=deployer)
    registry.set_factory(factory, sender=deployer)
    return factory

@fixture
def team(project, alice, factory):
    return project.Team.at(factory.deploy("A", sender=alice).return_value)

def test_add_team(deployer, registry, team):
    assert registry.num_teams() == 0
    assert registry.teams(0) == ZERO_ADDRESS
    assert registry.team_retirements(team) == 0
    assert not registry.is_team(team)
    registry.add_team(team, sender=deployer)
    assert registry.num_teams() == 1
    assert registry.teams(0) == team
    assert registry.team_retirements(team) == MAX
    assert registry.is_team(team)

    # cant add again
    with reverts():
        registry.add_team(team, sender=deployer)

def test_add_foreign_team(project, deployer, registry, implementation):
    factory = project.TeamFactory.deploy(registry, implementation, sender=deployer)
    team = factory.deploy("A", sender=deployer).return_value

    with reverts():
        registry.add_team(team, sender=deployer)

def test_retire_team(chain, deployer, genesis, registry, team):
    registry.add_team(team, sender=deployer)
    registry.retire_team(team, sender=deployer)
    assert registry.team_retirements(team) == 1
    assert registry.period() == 0
    assert registry.is_team(team)

    # cant retire more than once
    with reverts():
        registry.retire_team(team, sender=deployer)
    
    # starting from the next epoch, the team is no longer registered
    chain.pending_timestamp = genesis + PERIOD_LENGTH
    chain.mine()
    assert registry.period() == 1
    assert not registry.is_team(team)

def test_deprecate(project, deployer, genesis, registry):
    registry2 = project.TeamRegistry.deploy(genesis, sender=deployer)

    assert registry.successor() == ZERO_ADDRESS
    registry.deprecate(registry2, sender=deployer)
    assert registry.successor() == registry2

def test_migrate_team(project, deployer, alice, genesis, registry, factory, team):
    registry.add_team(team, sender=deployer)

    registry2 = project.TeamRegistry.deploy(genesis, sender=deployer)
    registry2.set_factory(factory, sender=deployer)

    # cant migrate before deprecating the registry
    with reverts():
        registry.migrate_team(team, sender=alice)

    registry.deprecate(registry2, sender=deployer)

    assert team.registry() == registry
    registry.migrate_team(team, sender=alice)
    assert team.registry() == registry2

    registry2.add_team(team, sender=deployer)
    assert registry2.is_team(team)
