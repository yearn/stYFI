from ape import reverts
from pytest import fixture

MAX = 2**256 - 1
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
PERIOD_LENGTH = 6 * 14 * 24 * 60 * 60

@fixture
def implementation(project, deployer):
    return project.Team.deploy(sender=deployer)

@fixture
def registry(chain, project, deployer, genesis, implementation):
    chain.pending_timestamp = genesis
    registry = project.TeamRegistry.deploy(genesis, sender=deployer)
    registry.set_implementation(implementation, sender=deployer)
    return registry

@fixture
def team(project, deployer, alice, registry):
    return project.Team.at(registry.add_team("A", alice, sender=deployer).return_value[1])

def test_add_team(project, deployer, alice, registry):
    assert registry.num_teams() == 0
    assert registry.teams(0) == ZERO_ADDRESS
    idx, team = registry.add_team("A", alice, sender=deployer).return_value
    team = project.Team.at(team)
    assert idx == 0
    assert registry.num_teams() == 1
    assert registry.teams(0) == team
    assert registry.team_retirements(team) == MAX
    assert registry.is_team(team)
    assert team.name() == "A"
    assert team.owner() == alice
    assert team.registry() == registry

    # cant add again
    with reverts():
        registry.add_team("A", alice, sender=deployer)

def test_retire_team(chain, deployer, genesis, registry, team):
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

def test_migrate_team(project, deployer, alice, genesis, registry, team):
    registry2 = project.TeamRegistry.deploy(genesis, sender=deployer)

    # cant migrate before deprecating the registry
    with reverts():
        registry.migrate_team(team, sender=alice)

    registry.deprecate(registry2, sender=deployer)

    assert team.registry() == registry
    registry.migrate_team(team, sender=alice)
    assert team.registry() == registry2
