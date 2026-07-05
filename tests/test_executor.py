from ape import reverts
from pytest import fixture

UNIT = 10**18

@fixture
def token(project, deployer):
    return project.MockToken.deploy(sender=deployer)

@fixture
def executor(project, deployer, alice):
    executor = project.Executor.deploy(sender=deployer)
    executor.set_operator(alice, True, sender=deployer)
    return executor

def test_execute(alice, bob, token, executor):
    # operator can execute a call
    token.mint(executor, 3 * UNIT, sender=alice)

    script = executor.script(token, token.transfer.encode_input(bob, UNIT))
    assert len(script) == 100
    # 32 (header) + 4 (identifier) + 32 (recipient) + 32 (amount) = 100

    assert token.balanceOf(executor) == 3 * UNIT
    assert token.balanceOf(bob) == 0
    executor.execute(script, sender=alice)
    assert token.balanceOf(executor) == 2 * UNIT
    assert token.balanceOf(bob) == UNIT

def test_execute_multiple(alice, bob, token, executor):
    # operator can execute multiple calls atomically
    token.mint(executor, 3 * UNIT, sender=alice)

    script = executor.script(token, token.transfer.encode_input(bob, UNIT)) + \
        executor.script(token, token.transfer.encode_input(alice, 2 * UNIT))
    assert len(script) == 200

    assert token.balanceOf(executor) == 3 * UNIT
    assert token.balanceOf(alice) == 0
    assert token.balanceOf(bob) == 0
    executor.execute(script, sender=alice)
    assert token.balanceOf(executor) == 0
    assert token.balanceOf(alice) == 2 * UNIT
    assert token.balanceOf(bob) == UNIT

def test_execute_permission(deployer, bob, token, executor):
    # only operator can execute calls
    token.mint(executor, UNIT, sender=bob)

    script = executor.script(token, token.transfer.encode_input(bob, UNIT))
    with reverts():
        executor.execute(script, sender=bob)

    assert token.balanceOf(bob) == 0
    executor.set_operator(bob, True, sender=deployer)
    executor.execute(script, sender=bob)
    assert token.balanceOf(bob) == UNIT

def test_set_operator(deployer, bob, executor):
    # management can add/remove operator
    assert not executor.operators(bob)
    executor.set_operator(bob, True, sender=deployer)
    assert executor.operators(bob)
    executor.set_operator(bob, False, sender=deployer)
    assert not executor.operators(bob)

def test_set_operator_permission(bob, executor):
    # only management can add/remove operator
    with reverts():
        executor.set_operator(bob, True, sender=bob)
