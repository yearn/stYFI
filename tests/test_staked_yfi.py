from ape import reverts
from pytest import fixture

ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'
UNIT = 10**18
BIG_MASK = 2**112 - 1
STREAM_DURATION = 14 * 24 * 60 * 60

@fixture
def hooks(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def staking(project, deployer, yfi, hooks):
    staking = project.StakedYFI.deploy(yfi, sender=deployer)
    staking.set_hooks(hooks, sender=deployer)
    return staking

def test_deposit(deployer, alice, bob, yfi, staking):
    # depositing increases supply and user balance
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(staking, UNIT, sender=alice)
    assert yfi.balanceOf(staking) == 0
    assert staking.totalSupply() == 0
    assert staking.balanceOf(bob) == 0
    staking.deposit(UNIT, bob, sender=alice)
    assert yfi.balanceOf(staking) == UNIT
    assert staking.totalSupply() == UNIT
    assert staking.balanceOf(bob) == UNIT

def test_deposit_add(deployer, alice, yfi, staking):
    # depositing adds to supply and user balance
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(staking, 3 * UNIT, sender=alice)
    staking.deposit(UNIT, sender=alice)
    staking.deposit(2 * UNIT, sender=alice)
    assert yfi.balanceOf(staking) == 3 * UNIT
    assert staking.totalSupply() == 3 * UNIT
    assert staking.balanceOf(alice) == 3 * UNIT

def test_deposit_multiple(deployer, alice, bob, yfi, staking):
    # deposits from multiple users updates supply and balance as expected
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(staking, UNIT, sender=alice)
    staking.deposit(UNIT, sender=alice)
    yfi.mint(bob, 2 * UNIT, sender=deployer)
    yfi.approve(staking, 2 * UNIT, sender=bob)
    staking.deposit(2 * UNIT, sender=bob)
    assert yfi.balanceOf(staking) == 3 * UNIT
    assert staking.totalSupply() == 3 * UNIT
    assert staking.balanceOf(alice) == UNIT
    assert staking.balanceOf(bob) == 2 * UNIT

def test_deposit_excessive(deployer, alice, yfi, staking):
    # cant deposit more than the balance
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(staking, UNIT, sender=alice)
    with reverts():
        staking.deposit(2 * UNIT, sender=alice)

def test_unstake(chain, deployer, alice, yfi, staking):
    # unstaking starts a stream
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(staking, 3 * UNIT, sender=alice)
    staking.deposit(3 * UNIT, sender=alice)
    assert staking.streams(alice) == (0, 0, 0)
    ts = chain.pending_timestamp
    staking.unstake(2 * UNIT, sender=alice)
    assert staking.totalSupply() == UNIT
    assert staking.balanceOf(alice) == UNIT
    assert staking.streams(alice) == (ts, 2 * UNIT, 0)

def test_unstake_excessive(deployer, alice, yfi, staking):
    # cant unstake more than balance
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(staking, UNIT, sender=alice)
    staking.deposit(UNIT, sender=alice)
    with reverts():
        staking.unstake(2 * UNIT, sender=alice)

def test_unstake_withdraw(chain, deployer, alice, bob, yfi, staking):
    # once a stream is active, tokens can be withdrawn over time
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(staking, 4 * UNIT, sender=alice)
    staking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    staking.unstake(4 * UNIT, sender=alice)
    assert staking.maxWithdraw(alice) == 0
    with chain.isolate():
        chain.pending_timestamp = ts + STREAM_DURATION // 4
        chain.mine()
        assert staking.maxWithdraw(alice) == UNIT
    with chain.isolate():
        chain.pending_timestamp = ts + STREAM_DURATION // 4
        staking.withdraw(UNIT, bob, sender=alice)
        assert staking.streams(alice) == (ts, 4 * UNIT, UNIT)
        assert staking.maxWithdraw(alice) == 0
        assert yfi.balanceOf(bob) == UNIT
    with chain.isolate():
        chain.pending_timestamp = ts + STREAM_DURATION // 2
        chain.mine()
        assert staking.maxWithdraw(alice) == 2 * UNIT
    with chain.isolate():
        chain.pending_timestamp = ts + STREAM_DURATION // 2
        staking.withdraw(2 * UNIT, bob, sender=alice)
        assert staking.streams(alice) == (ts, 4 * UNIT, 2 * UNIT)
        assert staking.maxWithdraw(alice) == 0
        assert yfi.balanceOf(bob) == 2 * UNIT

def test_unstake_withdraw_multiple(chain, deployer, alice, yfi, staking):
    # can withdraw multiple times from the stream
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(staking, 4 * UNIT, sender=alice)
    staking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    staking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION // 4
    staking.withdraw(UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION * 3 // 4
    with chain.isolate():
        chain.mine()
        assert staking.maxWithdraw(alice) == 2 * UNIT
    staking.withdraw(UNIT, sender=alice)
    assert staking.streams(alice) == (ts, 4 * UNIT, 2 * UNIT)
    assert staking.maxWithdraw(alice) == UNIT
    assert yfi.balanceOf(alice) == 2 * UNIT

def test_unstake_withdraw_excessive(chain, deployer, alice, yfi, staking):
    # cant withdraw more than has been streamed
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(staking, 4 * UNIT, sender=alice)
    staking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    staking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION // 4
    with reverts():
        staking.withdraw(2 * UNIT, sender=alice)

def test_unstake_withdraw_all(chain, deployer, alice, yfi, staking):
    # after stream has ended the full amount can be withdrawn
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(staking, 4 * UNIT, sender=alice)
    staking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    staking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp = ts + 2 * STREAM_DURATION
    chain.mine()
    assert staking.maxWithdraw(alice) == 4 * UNIT
    staking.withdraw(4 * UNIT, sender=alice)
    assert staking.maxWithdraw(alice) == 0

def test_unstake_withdraw_from(chain, deployer, alice, bob, yfi, staking):
    # third party with allowance can withdraw from a stream
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(staking, 4 * UNIT, sender=alice)
    staking.deposit(4 * UNIT, sender=alice)
    staking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp += STREAM_DURATION
    staking.approve(bob, 3 * UNIT, sender=alice)
    assert staking.allowance(alice, bob) == 3 * UNIT
    staking.withdraw(UNIT, deployer, alice, sender=bob)
    assert staking.maxWithdraw(alice) == 3 * UNIT
    assert staking.allowance(alice, bob) == 2 * UNIT
    assert yfi.balanceOf(deployer) == UNIT

def test_unstake_withdraw_from_excessive(chain, deployer, alice, bob, yfi, staking):
    # third party cant withdraw more than has been streamed
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(staking, 4 * UNIT, sender=alice)
    staking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    staking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION // 2
    staking.approve(bob, 3 * UNIT, sender=alice)
    with reverts():
        staking.withdraw(3 * UNIT, deployer, alice, sender=bob)

def test_unstake_withdraw_from_allowance(chain, deployer, alice, bob, yfi, staking):
    # third party cant withdraw more than their allowance
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(staking, 4 * UNIT, sender=alice)
    staking.deposit(4 * UNIT, sender=alice)
    staking.unstake(4 * UNIT, sender=alice)
    chain.pending_timestamp += STREAM_DURATION
    staking.approve(bob, UNIT, sender=alice)
    with reverts():
        staking.withdraw(2 * UNIT, deployer, alice, sender=bob)

def test_unstake_merge(chain, deployer, alice, yfi, staking):
    # unstaking with an existing stream adds unclaimed into the new one
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(staking, 4 * UNIT, sender=alice)
    staking.deposit(4 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    staking.unstake(3 * UNIT, sender=alice)
    chain.pending_timestamp = ts + STREAM_DURATION * 3 // 4
    staking.withdraw(2 * UNIT, sender=alice)
    ts = chain.pending_timestamp
    staking.unstake(UNIT, sender=alice)
    assert staking.streams(alice) == (ts, 2 * UNIT, 0)
    assert staking.maxWithdraw(alice) == 0

def test_unstake_instant(deployer, alice, yfi, hooks, staking):
    # whitelisted addresses are allowed to bypass the stream
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(staking, 3 * UNIT, sender=alice)
    staking.deposit(3 * UNIT, sender=alice)
    assert staking.streams(alice) == (0, 0, 0)
    assert staking.maxWithdraw(alice) == 0
    hooks.set_instant_withdrawal(alice, True, sender=deployer)
    assert staking.maxWithdraw(alice) == 3 * UNIT
    staking.withdraw(2 * UNIT, sender=alice)
    assert staking.totalSupply() == UNIT
    assert staking.balanceOf(alice) == UNIT
    assert staking.streams(alice) == (0, 0, 0)
    assert staking.maxWithdraw(alice) == UNIT

def test_unstake_instant_toggle(chain, deployer, alice, yfi, hooks, staking):
    # the instant withdrawal state could theoretically be toggled mid stream
    yfi.mint(alice, 5 * UNIT, sender=deployer)
    yfi.approve(staking, 5 * UNIT, sender=alice)
    staking.deposit(5 * UNIT, sender=alice)
    assert staking.streams(alice) == (0, 0, 0)
    assert staking.maxWithdraw(alice) == 0
    
    ts = chain.pending_timestamp
    staking.unstake(2 * UNIT, sender=alice)

    hooks.set_instant_withdrawal(alice, True, sender=deployer)
    chain.pending_timestamp = ts + STREAM_DURATION // 4
    staking.withdraw(UNIT, sender=alice)
    assert staking.streams(alice) == (ts, 2 * UNIT, UNIT)
    assert staking.maxWithdraw(alice) == 4 * UNIT

    hooks.set_instant_withdrawal(alice, False, sender=deployer)
    assert staking.maxWithdraw(alice) == 0
    # the claimed amount is now larger than what would be allowed if the flag had not toggled
    with reverts():
        staking.withdraw(UNIT // 2, sender=alice)

    chain.pending_timestamp = ts + STREAM_DURATION * 3 // 4
    staking.withdraw(UNIT // 2, sender=alice)
    assert staking.streams(alice) == (ts, 2 * UNIT, UNIT * 3 // 2)

def test_unstake_instant_toggle_additional(chain, deployer, alice, yfi, hooks, staking):
    # the instant withdrawal state could theoretically be toggled mid stream
    # withdrawing more than the stream finishes the stream and unstakes more
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(staking, 3 * UNIT, sender=alice)
    staking.deposit(3 * UNIT, sender=alice)
    assert staking.streams(alice) == (0, 0, 0)
    assert staking.maxWithdraw(alice) == 0
    
    ts = chain.pending_timestamp
    staking.unstake(UNIT, sender=alice)

    hooks.set_instant_withdrawal(alice, True, sender=deployer)
    chain.pending_timestamp = ts + STREAM_DURATION // 2
    staking.withdraw(2 * UNIT, sender=alice)
    assert staking.totalSupply() == UNIT
    assert staking.balanceOf(alice) == UNIT
    assert staking.streams(alice) == (0, 0, 0)
    assert staking.maxWithdraw(alice) == UNIT

def test_transfer(deployer, alice, bob, yfi, staking):
    # transferring updates balances but not supply
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(staking, 3 * UNIT, sender=alice)
    staking.deposit(3 * UNIT, sender=alice)
    staking.transfer(bob, UNIT, sender=alice)
    assert yfi.balanceOf(staking) == 3 * UNIT
    assert staking.totalSupply() == 3 * UNIT
    assert staking.balanceOf(alice) == 2 * UNIT
    assert staking.balanceOf(bob) == UNIT

def test_transfer_excessive(deployer, alice, bob, yfi, staking):
    # cant transfer more than balance
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(staking, UNIT, sender=alice)
    staking.deposit(UNIT, sender=alice)
    with reverts():
        staking.transfer(bob, 2 * UNIT, sender=alice)

def test_transfer_from(deployer, alice, bob, yfi, staking):
    # can transfer from other users if there's an allowance
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(staking, 4 * UNIT, sender=alice)
    staking.deposit(4 * UNIT, sender=alice)
    staking.approve(deployer, 3 * UNIT, sender=alice)
    staking.transferFrom(alice, bob, UNIT, sender=deployer)
    assert yfi.balanceOf(staking) == 4 * UNIT
    assert staking.allowance(alice, deployer) == 2 * UNIT
    assert staking.totalSupply() == 4 * UNIT
    assert staking.balanceOf(alice) == 3 * UNIT
    assert staking.balanceOf(bob) == UNIT

def test_transfer_from_excessive(deployer, alice, bob, yfi, staking):
    # cant transfer more from other user than the balance
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(staking, UNIT, sender=alice)
    staking.deposit(UNIT, sender=alice)
    staking.approve(bob, 2 * UNIT, sender=alice)
    with reverts():
        staking.transferFrom(alice, bob, 2 * UNIT, sender=bob)

def test_transfer_from_allowance_excessive(deployer, alice, bob, yfi, staking):
    # cant transfer more from other user than the allowance
    yfi.mint(alice, 2 * UNIT, sender=deployer)
    yfi.approve(staking, 2 * UNIT, sender=alice)
    staking.deposit(2 * UNIT, sender=alice)
    staking.approve(bob, UNIT, sender=alice)
    with reverts():
        staking.transferFrom(alice, bob, 2 * UNIT, sender=bob)

def test_approve(alice, bob, staking):
    # set allowance
    assert staking.allowance(alice, bob) == 0
    staking.approve(bob, UNIT, sender=alice)
    assert staking.allowance(alice, bob) == UNIT

def test_transfer_hook(deployer, alice, bob, yfi, hooks, staking):
    # transfering triggers the hook
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(staking, 3 * UNIT, sender=alice)
    staking.deposit(3 * UNIT, sender=alice)

    assert hooks.last_transfer() == (ZERO_ADDRESS, ZERO_ADDRESS, ZERO_ADDRESS, 0)
    staking.transfer(bob, UNIT, sender=alice)
    assert hooks.last_transfer() == (alice, alice, bob, UNIT)

def test_transfer_from_hook(deployer, alice, bob, yfi, hooks, staking):
    # transfering with allowance triggers the hook
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(staking, 3 * UNIT, sender=alice)
    staking.deposit(3 * UNIT, sender=alice)
    staking.approve(bob, UNIT, sender=alice)

    assert hooks.last_transfer() == (ZERO_ADDRESS, ZERO_ADDRESS, ZERO_ADDRESS, 0)
    staking.transferFrom(alice, bob, UNIT, sender=bob)
    assert hooks.last_transfer() == (bob, alice, bob, UNIT)

def test_stake_hook(deployer, alice, yfi, hooks, staking):
    # staking triggers the hook
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(staking, UNIT, sender=alice)

    assert hooks.last_stake() == (ZERO_ADDRESS, ZERO_ADDRESS, 0)
    staking.deposit(UNIT, sender=alice)
    assert hooks.last_stake() == (alice, alice, UNIT)

def test_stake_for_hook(deployer, alice, bob, yfi, hooks, staking):
    # staking for someone else triggers the hook
    yfi.mint(alice, UNIT, sender=deployer)
    yfi.approve(staking, UNIT, sender=alice)

    assert hooks.last_stake() == (ZERO_ADDRESS, ZERO_ADDRESS, 0)
    staking.deposit(UNIT, bob, sender=alice)
    assert hooks.last_stake() == (alice, bob, UNIT)

def test_unstake_hook(deployer, alice, yfi, hooks, staking):
    # unstaking triggers the hook
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(staking, 3 * UNIT, sender=alice)
    staking.deposit(3 * UNIT, sender=alice)

    assert hooks.last_unstake() == (ZERO_ADDRESS, 0)
    staking.unstake(UNIT, sender=alice)
    assert hooks.last_unstake() == (alice, UNIT)

def test_unstake_instant_hook(deployer, alice, yfi, hooks, staking):
    # instant withdraw triggers the hook
    yfi.mint(alice, 3 * UNIT, sender=deployer)
    yfi.approve(staking, 3 * UNIT, sender=alice)
    staking.deposit(3 * UNIT, sender=alice)

    assert hooks.last_unstake() == (ZERO_ADDRESS, 0)
    hooks.set_instant_withdrawal(alice, True, sender=alice)
    staking.withdraw(UNIT, sender=alice)
    assert hooks.last_unstake() == (alice, UNIT)
    
def test_unstake_instant_toggle_hook(deployer, alice, yfi, hooks, staking):
    # instant withdraw after toggling triggers the hook
    yfi.mint(alice, 4 * UNIT, sender=deployer)
    yfi.approve(staking, 4 * UNIT, sender=alice)
    staking.deposit(4 * UNIT, sender=alice)

    assert hooks.last_unstake() == (ZERO_ADDRESS, 0)
    staking.unstake(UNIT, sender=alice)
    assert hooks.last_unstake() == (alice, UNIT)
    hooks.set_instant_withdrawal(alice, True, sender=alice)
    staking.withdraw(3 * UNIT, sender=alice)
    assert hooks.last_unstake() == (alice, 2 * UNIT)

def test_set_hooks(project, deployer, staking, hooks):
    # hooks contract can be changed
    hooks2 = project.MockHooks.deploy(sender=deployer)
    assert staking.hooks() == hooks
    staking.set_hooks(hooks2, sender=deployer)
    assert staking.hooks() == hooks2

def test_set_hooks_permission(project, deployer, alice, staking):
    # only management can change rewards contract
    hooks2 = project.MockHooks.deploy(sender=deployer)
    with reverts():
        staking.set_hooks(hooks2, sender=alice)

def test_set_management(deployer, alice, staking):
    # management can propose a replacement
    assert staking.management() == deployer
    assert staking.pending_management() == ZERO_ADDRESS
    staking.set_management(alice, sender=deployer)
    assert staking.management() == deployer
    assert staking.pending_management() == alice

def test_set_management_undo(deployer, alice, staking):
    # proposed replacement can be undone
    staking.set_management(alice, sender=deployer)
    staking.set_management(ZERO_ADDRESS, sender=deployer)
    assert staking.management() == deployer
    assert staking.pending_management() == ZERO_ADDRESS

def test_set_management_permission(alice, staking):
    # only management can propose a replacement
    with reverts():
        staking.set_management(alice, sender=alice)

def test_accept_management(deployer, alice, staking):
    # replacement can accept management role
    staking.set_management(alice, sender=deployer)
    staking.accept_management(sender=alice)
    assert staking.management() == alice
    assert staking.pending_management() == ZERO_ADDRESS

def test_accept_management_early(alice, staking):
    # cant accept management role without being nominated
    with reverts():
        staking.accept_management(sender=alice)

def test_accept_management_wrong(deployer, alice, bob, staking):
    # cant accept management role without being the nominee
    staking.set_management(alice, sender=deployer)
    with reverts():
        staking.accept_management(sender=bob)
