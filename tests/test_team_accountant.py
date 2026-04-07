from ape import reverts
from pytest import fixture

INCREMENT = True
DECREMENT = False
UNIT = 10**18

@fixture
def accountant(project, deployer):
    accountant = project.TeamAccountant.deploy(sender=deployer)
    accountant.set_operator(deployer, True, sender=deployer)
    return accountant

def test_adjust_revenue(deployer, alice, bob, accountant):
    # increment
    assert accountant.team_revenues(alice, 0) == 0
    assert accountant.global_revenues(0) == 0
    accountant.adjust_revenue(alice, 0, UNIT, INCREMENT, sender=deployer)
    assert accountant.team_revenues(alice, 0) == UNIT
    assert accountant.global_revenues(0) == UNIT

    # increment more
    accountant.adjust_revenue(alice, 0, 3 * UNIT, INCREMENT, sender=deployer)
    assert accountant.team_revenues(alice, 0) == 4 * UNIT
    assert accountant.global_revenues(0) == 4 * UNIT

    # increment another team
    accountant.adjust_revenue(bob, 0, 2 * UNIT, INCREMENT, sender=deployer)
    assert accountant.team_revenues(bob, 0) == 2 * UNIT
    assert accountant.global_revenues(0) == 6 * UNIT

    # decrement
    accountant.adjust_revenue(alice, 0, 2 * UNIT, DECREMENT, sender=deployer)
    assert accountant.team_revenues(alice, 0) == 2 * UNIT
    assert accountant.global_revenues(0) == 4 * UNIT

    # cant decrement too much
    with reverts():
        accountant.adjust_revenue(bob, 0, 3 * UNIT, DECREMENT, sender=deployer)
    accountant.adjust_revenue(bob, 0, 2 * UNIT, DECREMENT, sender=deployer)

def test_adjust_revenue_permission(deployer, alice, accountant):
    with reverts():
        accountant.adjust_revenue(alice, 0, UNIT, INCREMENT, sender=alice)
    accountant.set_operator(alice, True, sender=deployer)
    accountant.adjust_revenue(alice, 0, UNIT, INCREMENT, sender=alice)

def test_adjust_cost(deployer, alice, bob, accountant):
    # increment
    assert accountant.team_costs(alice, 0) == 0
    assert accountant.global_costs(0) == 0
    accountant.adjust_cost(alice, 0, UNIT, INCREMENT, sender=deployer)
    assert accountant.team_costs(alice, 0) == UNIT
    assert accountant.global_costs(0) == UNIT

    # increment more
    accountant.adjust_cost(alice, 0, 3 * UNIT, INCREMENT, sender=deployer)
    assert accountant.team_costs(alice, 0) == 4 * UNIT
    assert accountant.global_costs(0) == 4 * UNIT

    # increment another team
    accountant.adjust_cost(bob, 0, 2 * UNIT, INCREMENT, sender=deployer)
    assert accountant.team_costs(bob, 0) == 2 * UNIT
    assert accountant.global_costs(0) == 6 * UNIT

    # decrement
    accountant.adjust_cost(alice, 0, 2 * UNIT, DECREMENT, sender=deployer)
    assert accountant.team_costs(alice, 0) == 2 * UNIT
    assert accountant.global_costs(0) == 4 * UNIT

    # cant decrement too much
    with reverts():
        accountant.adjust_cost(bob, 0, 3 * UNIT, DECREMENT, sender=deployer)
    accountant.adjust_cost(bob, 0, 2 * UNIT, DECREMENT, sender=deployer)

def test_adjust_cost_permission(deployer, alice, accountant):
    with reverts():
        accountant.adjust_cost(alice, 0, UNIT, INCREMENT, sender=alice)
    accountant.set_operator(alice, True, sender=deployer)
    accountant.adjust_cost(alice, 0, UNIT, INCREMENT, sender=alice)

def test_profit(deployer, alice, bob, accountant):
    # adding revenue increases profit
    assert accountant.team_profits(alice, 0) == 0
    assert accountant.global_profits(0) == 0
    accountant.adjust_revenue(alice, 0, 3 * UNIT, INCREMENT, sender=deployer)
    assert accountant.team_profits(alice, 0) == 3 * UNIT
    assert accountant.global_profits(0) == 3 * UNIT

    # adding cost decreases profit
    accountant.adjust_cost(alice, 0, UNIT, INCREMENT, sender=deployer)
    assert accountant.team_profits(alice, 0) == 2 * UNIT
    assert accountant.global_profits(0) == 2 * UNIT

    # adding cost to another team affects global profitability
    accountant.adjust_cost(bob, 0, 3 * UNIT, INCREMENT, sender=deployer)
    assert accountant.team_profits(alice, 0) == 2 * UNIT
    assert accountant.global_profits(0) == 0

def test_loss(deployer, alice, bob, accountant):
    # adding revenue increases loss
    assert accountant.team_losses(alice, 0) == 0
    assert accountant.global_losses(0) == 0
    accountant.adjust_cost(alice, 0, 3 * UNIT, INCREMENT, sender=deployer)
    assert accountant.team_losses(alice, 0) == 3 * UNIT
    assert accountant.global_losses(0) == 3 * UNIT

    # adding revneue decreases loss
    accountant.adjust_revenue(alice, 0, UNIT, INCREMENT, sender=deployer)
    assert accountant.team_losses(alice, 0) == 2 * UNIT
    assert accountant.global_losses(0) == 2 * UNIT

    # adding revenue of another team affects global losses
    accountant.adjust_revenue(bob, 0, 3 * UNIT, INCREMENT, sender=deployer)
    assert accountant.team_losses(alice, 0) == 2 * UNIT
    assert accountant.global_losses(0) == 0

def test_set_operator(deployer, alice, accountant):
    assert not accountant.operators(alice)
    accountant.set_operator(alice, True, sender=deployer)
    assert accountant.operators(alice)
    accountant.set_operator(alice, False, sender=deployer)
    assert not accountant.operators(alice)

def test_set_operator_permission(deployer, alice, accountant):
    with reverts():
        accountant.set_operator(alice, True, sender=alice)
    accountant.set_operator(alice, True, sender=deployer)
