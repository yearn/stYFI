from ape import reverts
from pytest import fixture

ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'
UNIT = 10**18
BIG_MASK = 2**112 - 1
STREAM_DURATION = 14 * 24 * 60 * 60

@fixture
def underlying(project, deployer):
    return project.MockToken.deploy(sender=deployer)

@fixture
def hooks(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def depositor(project, deployer, underlying, hooks):
    depositor = project.LiquidLockerDepositor.deploy(underlying, 4, "", "", sender=deployer)
    depositor.set_hooks(hooks, sender=deployer)
    return depositor

def test_deposit(deployer, alice, bob, underlying, depositor):
    # depositing increases supply and user balance
    underlying.mint(alice, UNIT, sender=deployer)
    underlying.approve(depositor, UNIT, sender=alice)
    assert underlying.balanceOf(depositor) == 0
    assert depositor.totalSupply() == 0
    assert depositor.balanceOf(bob) == 0
    depositor.deposit(UNIT, bob, sender=alice)
    assert underlying.balanceOf(depositor) == UNIT
    assert depositor.totalSupply() == UNIT // 4
    assert depositor.balanceOf(bob) == UNIT // 4

def test_deposit_add(deployer, alice, underlying, depositor):
    # depositing adds to supply and user balance
    underlying.mint(alice, 3 * UNIT, sender=deployer)
    underlying.approve(depositor, 3 * UNIT, sender=alice)
    depositor.deposit(UNIT, sender=alice)
    depositor.deposit(2 * UNIT, sender=alice)
    assert underlying.balanceOf(depositor) == 3 * UNIT
    assert depositor.totalSupply() == 3 * UNIT // 4
    assert depositor.balanceOf(alice) == 3 * UNIT // 4

def test_deposit_multiple(deployer, alice, bob, underlying, depositor):
    # deposits from multiple users updates supply and balance as expected
    underlying.mint(alice, UNIT, sender=deployer)
    underlying.approve(depositor, UNIT, sender=alice)
    depositor.deposit(UNIT, sender=alice)
    underlying.mint(bob, 2 * UNIT, sender=deployer)
    underlying.approve(depositor, 2 * UNIT, sender=bob)
    depositor.deposit(2 * UNIT, sender=bob)
    assert underlying.balanceOf(depositor) == 3 * UNIT
    assert depositor.totalSupply() == 3 * UNIT // 4
    assert depositor.balanceOf(alice) == UNIT // 4
    assert depositor.balanceOf(bob) == 2 * UNIT // 4

def test_deposit_excessive(deployer, alice, underlying, depositor):
    # cant deposit more than the balance
    underlying.mint(alice, UNIT, sender=deployer)
    underlying.approve(depositor, UNIT, sender=alice)
    with reverts():
        depositor.deposit(2 * UNIT, sender=alice)

def test_unstake(chain, deployer, alice, underlying, depositor):
    # unstaking starts a stream
    underlying.mint(alice, 3 * UNIT, sender=deployer)
    underlying.approve(depositor, 3 * UNIT, sender=alice)
    depositor.deposit(3 * UNIT, sender=alice)
    assert depositor.streams(alice) == (0, 0, 0)
    ts = chain.pending_timestamp
    depositor.unstake(2 * UNIT // 4, sender=alice)
    assert depositor.totalSupply() == UNIT // 4
    assert depositor.balanceOf(alice) == UNIT // 4
    assert depositor.streams(alice) == (ts, 2 * UNIT // 4, 0)

def test_unstake_excessive(deployer, alice, underlying, depositor):
    # cant unstake more than balance
    underlying.mint(alice, UNIT, sender=deployer)
    underlying.approve(depositor, UNIT, sender=alice)
    depositor.deposit(UNIT, sender=alice)
    with reverts():
        depositor.unstake(2 * UNIT // 4, sender=alice)

def test_unstake_withdraw(chain, deployer, alice, bob, underlying, depositor):
    # once a stream is active, tokens can be withdrawn over time
    underlying.mint(alice, 4 * UNIT, sender=deployer)
    underlying.approve(depositor, 4 * UNIT, sender=alice)
    depositor.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    depositor.unstake(4 * UNIT // 4, sender=alice)
    assert depositor.maxWithdraw(alice) == 0
    chain.pending_timestamp = ts + STREAM_DURATION // 4
    with chain.isolate():
        chain.mine()
        assert depositor.maxWithdraw(alice) == UNIT
        assert depositor.maxRedeem(alice) == UNIT // 4
    with chain.isolate():
        depositor.withdraw(UNIT, bob, sender=alice)
        assert depositor.streams(alice) == (ts, 4 * UNIT // 4, UNIT // 4)
        assert depositor.maxWithdraw(alice) == 0
        assert depositor.maxRedeem(alice) == 0
        assert underlying.balanceOf(bob) == UNIT
    with chain.isolate():
        depositor.redeem(UNIT // 4, bob, sender=alice)
        assert depositor.streams(alice) == (ts, 4 * UNIT // 4, UNIT // 4)
        assert depositor.maxWithdraw(alice) == 0
        assert depositor.maxRedeem(alice) == 0
        assert underlying.balanceOf(bob) == UNIT
    chain.pending_timestamp = ts + STREAM_DURATION // 2
    with chain.isolate():
        chain.mine()
        assert depositor.maxWithdraw(alice) == 2 * UNIT
        assert depositor.maxRedeem(alice) == 2 * UNIT // 4
    with chain.isolate():
        depositor.withdraw(2 * UNIT, bob, sender=alice)
        assert depositor.streams(alice) == (ts, 4 * UNIT // 4, 2 * UNIT // 4)
        assert depositor.maxWithdraw(alice) == 0
        assert depositor.maxRedeem(alice) == 0
        assert underlying.balanceOf(bob) == 2 * UNIT
    with chain.isolate():
        depositor.redeem(2 * UNIT // 4, bob, sender=alice)
        assert depositor.streams(alice) == (ts, 4 * UNIT // 4, 2 * UNIT // 4)
        assert depositor.maxWithdraw(alice) == 0
        assert depositor.maxRedeem(alice) == 0
        assert underlying.balanceOf(bob) == 2 * UNIT

def test_unstake_withdraw_multiple(chain, deployer, alice, underlying, depositor):
    # can withdraw multiple times from the stream
    underlying.mint(alice, 4 * UNIT, sender=deployer)
    underlying.approve(depositor, 4 * UNIT, sender=alice)
    depositor.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    depositor.unstake(4 * UNIT // 4, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION // 2
    depositor.withdraw(UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION * 3 // 4
    with chain.isolate():
        chain.mine()
        assert depositor.maxWithdraw(alice) == 2 * UNIT
    depositor.withdraw(UNIT, sender=alice)
    assert depositor.streams(alice) == (ts, 4 * UNIT // 4, 2 * UNIT // 4)
    assert depositor.maxWithdraw(alice) == UNIT
    assert underlying.balanceOf(alice) == 2 * UNIT

def test_unstake_withdraw_excessive(chain, deployer, alice, underlying, depositor):
    # cant withdraw more than has been streamed
    underlying.mint(alice, 4 * UNIT, sender=deployer)
    underlying.approve(depositor, 4 * UNIT, sender=alice)
    depositor.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    depositor.unstake(4 * UNIT // 4, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION // 4
    with reverts():
        depositor.withdraw(2 * UNIT, sender=alice)

def test_unstake_withdraw_all(chain, deployer, alice, underlying, depositor):
    # after stream has ended the full amount can be withdrawn
    underlying.mint(alice, 4 * UNIT, sender=deployer)
    underlying.approve(depositor, 4 * UNIT, sender=alice)
    depositor.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    depositor.unstake(4 * UNIT // 4, sender=alice)
    chain.pending_timestamp = ts + 2 * STREAM_DURATION
    chain.mine()
    assert depositor.maxWithdraw(alice) == 4 * UNIT
    assert depositor.maxRedeem(alice) == 4 * UNIT // 4
    depositor.withdraw(4 * UNIT, sender=alice)
    assert depositor.maxWithdraw(alice) == 0
    assert depositor.maxRedeem(alice) == 0

def test_unstake_withdraw_from(chain, deployer, alice, bob, underlying, depositor):
    # third party with allowance can withdraw from a stream
    underlying.mint(alice, 4 * UNIT, sender=deployer)
    underlying.approve(depositor, 4 * UNIT, sender=alice)
    depositor.deposit(4 * UNIT, sender=alice)
    depositor.unstake(4 * UNIT // 4, sender=alice)
    chain.pending_timestamp += STREAM_DURATION
    depositor.approve(bob, 3 * UNIT // 4, sender=alice)
    assert depositor.allowance(alice, bob) == 3 * UNIT // 4
    depositor.withdraw(UNIT, deployer, alice, sender=bob)
    assert depositor.maxWithdraw(alice) == 3 * UNIT
    assert depositor.allowance(alice, bob) == 2 * UNIT // 4
    assert underlying.balanceOf(deployer) == UNIT

def test_unstake_withdraw_from_excessive(chain, deployer, alice, bob, underlying, depositor):
    # third party cant withdraw more than has been streamed
    underlying.mint(alice, 4 * UNIT, sender=deployer)
    underlying.approve(depositor, 4 * UNIT, sender=alice)
    depositor.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    depositor.unstake(4 * UNIT // 4, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION // 2
    depositor.approve(bob, 3 * UNIT // 4, sender=alice)
    with reverts():
        depositor.withdraw(3 * UNIT, deployer, alice, sender=bob)

def test_unstake_withdraw_from_allowance(chain, deployer, alice, bob, underlying, depositor):
    # third party cant withdraw more than their allowance
    underlying.mint(alice, 4 * UNIT, sender=deployer)
    underlying.approve(depositor, 4 * UNIT, sender=alice)
    depositor.deposit(4 * UNIT, sender=alice)
    depositor.unstake(4 * UNIT // 4, sender=alice)
    chain.pending_timestamp += STREAM_DURATION
    depositor.approve(bob, UNIT // 4, sender=alice)
    with reverts():
        depositor.withdraw(2 * UNIT, deployer, alice, sender=bob)

def test_unstake_merge(chain, deployer, alice, underlying, depositor):
    # unstaking with an existing stream adds unclaimed into the new one
    underlying.mint(alice, 4 * UNIT, sender=deployer)
    underlying.approve(depositor, 4 * UNIT, sender=alice)
    depositor.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    chain.pending_timestamp = ts
    depositor.unstake(3 * UNIT // 4, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION * 3 // 4
    depositor.withdraw(2 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    chain.pending_timestamp = ts
    depositor.unstake(UNIT // 4, sender=alice)
    assert depositor.streams(alice) == (ts, 2 * UNIT // 4, 0)
    assert depositor.maxWithdraw(alice) == 0
    assert depositor.maxRedeem(alice) == 0

def test_approve(alice, bob, depositor):
    # set allowance
    assert depositor.allowance(alice, bob) == 0
    depositor.approve(bob, UNIT, sender=alice)
    assert depositor.allowance(alice, bob) == UNIT

def test_stake_hook(deployer, alice, underlying, hooks, depositor):
    # staking triggers the hook
    underlying.mint(alice, UNIT, sender=deployer)
    underlying.approve(depositor, UNIT, sender=alice)

    assert hooks.last_stake() == (ZERO_ADDRESS, ZERO_ADDRESS, 0)
    depositor.deposit(UNIT, sender=alice)
    assert hooks.last_stake() == (alice, alice, UNIT // 4)

def test_stake_for_hook(deployer, alice, bob, underlying, hooks, depositor):
    # staking for someone else triggers the hook
    underlying.mint(alice, UNIT, sender=deployer)
    underlying.approve(depositor, UNIT, sender=alice)

    assert hooks.last_stake() == (ZERO_ADDRESS, ZERO_ADDRESS, 0)
    depositor.deposit(UNIT, bob, sender=alice)
    assert hooks.last_stake() == (alice, bob, UNIT // 4)

def test_unstake_hook(deployer, alice, underlying, hooks, depositor):
    # unstaking triggers the hook
    underlying.mint(alice, 3 * UNIT, sender=deployer)
    underlying.approve(depositor, 3 * UNIT, sender=alice)
    depositor.deposit(3 * UNIT, sender=alice)

    assert hooks.last_unstake() == (ZERO_ADDRESS, 0)
    depositor.unstake(UNIT // 4, sender=alice)
    assert hooks.last_unstake() == (alice, UNIT // 4)

def test_set_hooks(project, deployer, depositor, hooks):
    # hooks contract can be changed
    hooks2 = project.MockHooks.deploy(sender=deployer)
    assert depositor.hooks() == hooks
    depositor.set_hooks(hooks2, sender=deployer)
    assert depositor.hooks() == hooks2

def test_set_hooks_permission(project, deployer, alice, depositor):
    # only management can change rewards contract
    hooks2 = project.MockHooks.deploy(sender=deployer)
    with reverts():
        depositor.set_hooks(hooks2, sender=alice)

def test_set_management(deployer, alice, depositor):
    # management can propose a replacement
    assert depositor.management() == deployer
    assert depositor.pending_management() == ZERO_ADDRESS
    depositor.set_management(alice, sender=deployer)
    assert depositor.management() == deployer
    assert depositor.pending_management() == alice

def test_set_management_undo(deployer, alice, depositor):
    # proposed replacement can be undone
    depositor.set_management(alice, sender=deployer)
    depositor.set_management(ZERO_ADDRESS, sender=deployer)
    assert depositor.management() == deployer
    assert depositor.pending_management() == ZERO_ADDRESS

def test_set_management_permission(alice, depositor):
    # only management can propose a replacement
    with reverts():
        depositor.set_management(alice, sender=alice)

def test_accept_management(deployer, alice, depositor):
    # replacement can accept management role
    depositor.set_management(alice, sender=deployer)
    depositor.accept_management(sender=alice)
    assert depositor.management() == alice
    assert depositor.pending_management() == ZERO_ADDRESS

def test_accept_management_early(alice, depositor):
    # cant accept management role without being nominated
    with reverts():
        depositor.accept_management(sender=alice)

def test_accept_management_wrong(deployer, alice, bob, depositor):
    # cant accept management role without being the nominee
    depositor.set_management(alice, sender=deployer)
    with reverts():
        depositor.accept_management(sender=bob)
