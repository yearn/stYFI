from ape import reverts
from pytest import fixture

UNIT = 10**18
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

@fixture
def hooks(project, deployer):
    return project.MockYBCMemberHooks.deploy(sender=deployer)

@fixture
def ybc(project, deployer, alice, hooks):
    ybc = project.YBC.deploy(sender=deployer)
    ybc.set_hooks(hooks, sender=deployer)
    ybc.set_operator(alice, True, sender=deployer)
    return ybc

def test_call(project, deployer, alice, ybc):
    # operators can call arbitrary functions on behalf of the YBC
    token = project.MockToken.deploy(sender=deployer)
    token.mint(ybc, 3 * UNIT, sender=deployer)

    assert token.balanceOf(ybc) == 3 * UNIT
    assert token.balanceOf(alice) == 0
    ybc.call(token, token.transfer.encode_input(alice, UNIT), sender=alice)
    assert token.balanceOf(ybc) == 2 * UNIT
    assert token.balanceOf(alice) == UNIT

def test_call_return(project, deployer, alice, ybc):
    # call can return data
    token = project.MockToken.deploy(sender=deployer)
    token.mint(alice, 3 * UNIT, sender=deployer)
    data = ybc.call(token, token.balanceOf.encode_input(alice), sender=alice).return_value
    assert int.from_bytes(data) == 3 * UNIT

def test_call_permission(project, deployer, alice, bob, ybc):
    # only operators can call arbitrary functions on behalf of the YBC
    token = project.MockToken.deploy(sender=deployer)
    token.mint(ybc, 3 * UNIT, sender=deployer)

    with reverts():
        ybc.call(token, token.transfer.encode_input(alice, UNIT), sender=bob)
    ybc.call(token, token.transfer.encode_input(alice, UNIT), sender=alice)

def test_add_member(alice, bob, hooks, ybc):
    # operators can add members
    assert ybc.num_members() == 0
    assert not ybc.members(alice)
    assert hooks.last_add() == ZERO_ADDRESS
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=alice)
    assert ybc.num_members() == 1
    assert ybc.members(alice)
    assert hooks.last_add() == alice

    # add another
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=alice)
    assert ybc.num_members() == 2
    assert ybc.members(bob)
    assert hooks.last_add() == bob

def test_add_member_multiple(alice, bob, ybc):
    # cant add members more than once
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=alice)
    with reverts():
        ybc.call(ybc, ybc.add_member.encode_input(bob), sender=alice)

def test_add_member_permission(alice, bob, ybc):
    # only operators can add members
    with reverts():
        ybc.call(ybc, ybc.add_member.encode_input(bob), sender=bob)
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=alice)

def test_remove_member(alice, bob, hooks, ybc):
    # operators can remove members
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=alice)
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=alice)

    assert hooks.last_remove() == ZERO_ADDRESS
    ybc.call(ybc, ybc.remove_member.encode_input(alice), sender=alice)
    assert ybc.num_members() == 1
    assert not ybc.members(alice)
    assert hooks.last_remove() == alice

def test_remove_member_multiple(alice, bob, ybc):
    # cant remove members more than once
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=alice)
    ybc.call(ybc, ybc.remove_member.encode_input(bob), sender=alice)
    with reverts():
        ybc.call(ybc, ybc.remove_member.encode_input(bob), sender=alice)

def test_remove_member_permission(alice, bob, ybc):
    # only operators can remove members
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=alice)
    with reverts():
        ybc.call(ybc, ybc.remove_member.encode_input(bob), sender=bob)
    ybc.call(ybc, ybc.remove_member.encode_input(bob), sender=alice)

def test_set_hooks(project, deployer, alice, hooks, ybc):
    # management can set hooks
    hooks2 = project.MockYBCMemberHooks.deploy(sender=deployer)
    assert ybc.hooks() == hooks
    ybc.set_hooks(hooks2, sender=deployer)
    assert ybc.hooks() == hooks2

    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=alice)
    assert hooks.last_add() == ZERO_ADDRESS
    assert hooks2.last_add() == alice

def test_set_hooks_permission(deployer, alice, ybc):
    # only management can set hooks
    with reverts():
        ybc.set_hooks(alice, sender=alice)
    ybc.set_hooks(alice, sender=deployer)

def test_set_operator(deployer, bob, ybc):
    # management can (un)set operators
    assert not ybc.operators(bob)
    ybc.set_operator(bob, True, sender=deployer)
    assert ybc.operators(bob)

    ybc.set_operator(bob, False, sender=deployer)
    assert not ybc.operators(bob)

def test_set_operator_permission(deployer, bob, ybc):
    # only management can (un)set operators
    with reverts():
        ybc.set_operator(bob, True, sender=bob)
    ybc.set_operator(bob, True, sender=deployer)
