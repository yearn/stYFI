from ape import reverts
from eth_hash.auto import keccak
from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
DECAY_LENGTH = 24 * 60 * 60
UNIT = 10**18
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
PROPOSED  = 1 << 0
RETRACTED = 1 << 1
VOTING    = 1 << 2
PASSED    = 1 << 3
FAILED    = 1 << 4
EXECUTED  = 1 << 5
EXPIRED   = 1 << 6
INVALID   = 1 << 7
FLAGGED   = 1 << 8
VETOED    = 1 << 9

IPFS_HASH = "0xabcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
DUMMY_SCRIPT = b":)"

@fixture
def measure(project, deployer, alice, bob):
    measure = project.MockWeightAggregator.deploy(sender=deployer)
    measure.set_weight(alice, UNIT, sender=deployer)
    measure.set_weight(bob, UNIT, sender=deployer)
    return measure

@fixture
def hooks(project, deployer):
    return project.MockHooks.deploy(sender=deployer)

@fixture
def blacklist(project, deployer):
    return project.StakingMiddleware.deploy(ZERO_ADDRESS, ZERO_ADDRESS, ZERO_ADDRESS, sender=deployer)

@fixture
def executor(project, deployer):
    return project.Executor.deploy(sender=deployer)

@fixture
def voting(chain, project, deployer, genesis, measure, hooks, blacklist, executor):
    chain.pending_timestamp = genesis + EPOCH_LENGTH
    voting = project.Voting.deploy(genesis, sender=deployer)
    voting.set_weight_measure(measure, sender=deployer)
    voting.set_hooks(hooks, sender=deployer)
    voting.set_propose_parameters(10**18, 0, blacklist, sender=deployer)
    voting.set_vote_parameters(EPOCH_LENGTH // 2, deployer, sender=deployer)
    voting.set_execute_parameters(0, False, executor, sender=deployer)
    executor.set_operator(voting, True, sender=deployer)
    return voting

@fixture
def token(project, deployer):
    return project.MockToken.deploy(sender=deployer)

def test_propose(chain, alice, hooks, voting):
    # proposals can be created
    assert voting.last_proposed(alice) == 0
    assert hooks.last_proposer() == ZERO_ADDRESS
    assert voting.num_proposals() == 0
    assert voting.proposals(0).proposer == ZERO_ADDRESS
    assert voting.status(0) == INVALID
    ts = chain.pending_timestamp
    chain.pending_timestamp = ts
    id = voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice).return_value
    assert id == 0
    assert voting.last_proposed(alice) == ts
    assert hooks.last_proposer() == alice
    assert voting.num_proposals() == 1
    assert voting.proposals(0).proposer == alice
    assert voting.status(0) == PROPOSED
    prop = voting.proposals(0)
    assert prop.proposer == alice
    assert prop.epoch == 2
    assert prop.ipfs.hex() == IPFS_HASH[2:]
    assert prop.script_hash == keccak(DUMMY_SCRIPT)

    id = voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice).return_value
    assert id == 1
    assert voting.num_proposals() == 2
    assert voting.proposals(1).proposer == alice
    assert voting.status(1) == PROPOSED
    assert hooks.last_proposal() == 1

def test_propose_min_weight(deployer, alice, measure, blacklist, voting):
    # proposals can only be created if the minimum weight is met
    voting.set_propose_parameters(2 * UNIT, DECAY_LENGTH, blacklist, sender=deployer)
    measure.set_weight(alice, 2 * UNIT - 1, sender=alice)
    with reverts():
        voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)

    measure.set_weight(alice, 2 * UNIT, sender=alice)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)

def test_propose_cooldown(chain, deployer, alice, bob, blacklist, voting):
    # proposals can only be created if the user-specific cooldown has lapsed
    voting.set_propose_parameters(UNIT, DECAY_LENGTH, blacklist, sender=deployer)

    ts = chain.pending_timestamp
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)

    # bob can still propose
    chain.pending_timestamp = ts + DECAY_LENGTH - 1
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=bob)

    # but alice cant
    chain.pending_timestamp = ts + DECAY_LENGTH - 1
    with reverts():
        voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    
    chain.pending_timestamp = ts + DECAY_LENGTH
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)

def test_propose_blacklist(deployer, alice, blacklist, voting):
    # proposals cant be created if the caller is blacklisted
    blacklist.set_blacklist(alice, True, sender=deployer)
    with reverts():
        voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)

    blacklist.set_blacklist(alice, False, sender=deployer)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)

def test_retract(alice, hooks, voting):
    # proposals can be retracted
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    with reverts():
        # non-existing proposal
        voting.retract(1, sender=alice)
    
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    assert voting.status(1) == PROPOSED
    assert not voting.proposals(1).retracted
    voting.retract(1, sender=alice)
    assert voting.status(1) == RETRACTED
    assert voting.proposals(1).retracted
    assert hooks.last_retract() == 1

    # cant retract again
    with reverts():
        voting.retract(1, sender=alice)

def test_retract_late(chain, deployer, alice, genesis, hooks, voting):
    # proposals can only be retracted if there are no votes
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    
    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    chain.mine()
    voting.vote(alice, 0, 10000, 10000, sender=deployer)

    # cant retract a proposal with votes
    with reverts():
        voting.retract(0, sender=alice)

    # but can still retract a proposal without votes
    voting.retract(1, sender=alice)
    assert voting.status(1) == RETRACTED
    assert hooks.last_retract() == 1

def test_retract_permission(alice, bob, voting):
    # proposals can only be retracted by the author
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)

    with reverts():
        voting.retract(0, sender=bob)
    voting.retract(0, sender=alice)

def test_flag(deployer, alice, bob, hooks, voting):
    # proposals can be flagged
    voting.set_operator(bob, sender=deployer)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    with reverts():
        # non-existing proposal
        voting.flag(1, ".", sender=bob)
    
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    assert voting.status(1) == PROPOSED
    assert not voting.proposals(1).retracted
    assert not voting.proposals(1).flagged
    voting.flag(1, ".", sender=bob)
    assert voting.status(1) == FLAGGED
    assert voting.proposals(1).retracted
    assert voting.proposals(1).flagged
    assert hooks.last_retract() == 1

    # cant flag again
    with reverts():
        voting.flag(1, ".", sender=bob)

def test_flag_late(chain, deployer, alice, bob, genesis, hooks, voting):
    # proposals can only be flagged if there are no votes
    voting.set_operator(bob, sender=deployer)

    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    
    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    chain.mine()
    voting.vote(alice, 0, 10000, 10000, sender=deployer)

    # cant flag a proposal with votes
    with reverts():
        voting.flag(0, ".", sender=bob)

    # but can still retract a proposal without votes
    voting.flag(1, ".", sender=bob)
    assert voting.status(1) == FLAGGED
    assert hooks.last_retract() == 1

def test_veto(deployer, alice, bob, hooks, voting):
    # proposals can be vetoed
    voting.set_guardian(bob, sender=deployer)
    voting.accept_guardian(sender=bob)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    with reverts():
        # non-existing proposal
        voting.veto(1, ".", sender=bob)
    
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    assert voting.status(1) == PROPOSED
    assert not voting.proposals(1).retracted
    assert not voting.proposals(1).vetoed
    voting.veto(1, ".", sender=bob)
    assert voting.status(1) == VETOED
    assert voting.proposals(1).retracted
    assert voting.proposals(1).vetoed
    assert hooks.last_retract() == 1

    # cant veto again
    with reverts():
        voting.veto(1, ".", sender=bob)

def test_veto_votes(chain, deployer, alice, bob, genesis, hooks, voting):
    # proposals with votes that get vetoed dont get retracted
    voting.set_guardian(bob, sender=deployer)
    voting.accept_guardian(sender=bob)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    chain.mine()
    voting.vote(alice, 1, 10000, 10000, sender=deployer)
    
    assert voting.status(1) == VOTING
    voting.veto(1, ".", sender=bob)
    assert voting.status(1) == VETOED
    assert not voting.proposals(1).retracted
    assert voting.proposals(1).vetoed
    assert hooks.last_retract() == 0

def test_veto_passed(chain, deployer, alice, bob, genesis, hooks, voting):
    # passed proposals can still get vetoed
    voting.set_guardian(bob, sender=deployer)
    voting.accept_guardian(sender=bob)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice)

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    chain.mine()
    voting.vote(alice, 1, 10000, 10000, sender=deployer)
    chain.pending_timestamp += EPOCH_LENGTH
    chain.mine()
    
    assert voting.status(1) == PASSED
    voting.veto(1, ".", sender=bob)
    assert voting.status(1) == VETOED
    assert not voting.proposals(1).retracted
    assert voting.proposals(1).vetoed
    assert hooks.last_retract() == 0

def test_vote(chain, genesis, deployer, alice, bob, hooks, voting):
    # proposals can be voted on
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice).return_value

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    chain.mine()

    assert voting.status(0) == VOTING
    assert not voting.voted(alice, 0)
    voting.vote(alice, 0, 5000, 10000, sender=deployer)
    assert voting.voted(alice, 0)
    prop = voting.proposals(0)
    assert hooks.last_voter() == alice
    assert prop.votes == UNIT // 2
    assert prop.yea == UNIT // 2

    voting.vote(bob, 0, 10000, 8000, sender=deployer)
    prop = voting.proposals(0)
    assert prop.votes == 3 * UNIT // 2
    assert prop.yea == UNIT * 13 // 10

def test_vote_update(chain, genesis, deployer, alice, bob, voting):
    # votes can be updated
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice).return_value

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    chain.mine()

    assert voting.status(0) == VOTING
    voting.vote(alice, 0, 10000, 10000, sender=deployer)
    voting.vote(bob, 0, 10000, 10000, sender=deployer)
    prop = voting.proposals(0)
    assert prop.votes == 2 * UNIT
    assert prop.yea == 2 * UNIT
    voting.vote(bob, 0, 5000, 8000, sender=deployer)
    prop = voting.proposals(0)
    assert prop.votes == 3 * UNIT // 2
    assert prop.yea == UNIT * 14 // 10

def test_vote_early(chain, genesis, deployer, alice, voting):
    # proposals cant be voted on before voting opens
    voting.set_vote_parameters(10, deployer, sender=deployer)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice).return_value

    ts = genesis + 3 * EPOCH_LENGTH - 10
    chain.pending_timestamp = ts - 1
    chain.mine()

    assert voting.status(0) == PROPOSED
    with reverts():
        chain.pending_timestamp = ts - 1
        voting.vote(alice, 0, 5000, 10000, sender=deployer)

    chain.pending_timestamp = ts
    chain.mine()

    assert voting.status(0) == VOTING
    voting.vote(alice, 0, 5000, 10000, sender=deployer)

def test_vote_late(chain, genesis, deployer, alice, voting):
    # proposals cant be voted on after voting closes
    voting.set_vote_parameters(10, deployer, sender=deployer)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice).return_value

    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    chain.mine()

    assert voting.status(0) == FAILED
    with reverts():
        voting.vote(alice, 0, 5000, 10000, sender=deployer)

def test_vote_retracted(chain, genesis, deployer, alice, bob, voting):
    # retracted proposals cant be voted on
    voting.set_operator(bob, sender=deployer)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice).return_value
    voting.retract(0, sender=alice)

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    chain.mine()

    assert voting.status(0) == RETRACTED
    with reverts():
        voting.vote(alice, 0, 5000, 10000, sender=deployer)

def test_vote_flagged(chain, genesis, deployer, alice, bob, voting):
    # flagged proposals cant be voted on
    voting.set_operator(bob, sender=deployer)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice).return_value
    voting.flag(0, ".", sender=bob)

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    chain.mine()

    assert voting.status(0) == FLAGGED
    with reverts():
        voting.vote(alice, 0, 5000, 10000, sender=deployer)

def test_vote_vetoed(chain, genesis, deployer, alice, bob, voting):
    # early vetoed proposals cant be voted on
    voting.set_guardian(bob, sender=deployer)
    voting.accept_guardian(sender=bob)
    voting.propose(IPFS_HASH, DUMMY_SCRIPT, sender=alice).return_value
    voting.veto(0, ".", sender=bob)

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    chain.mine()

    assert voting.status(0) == VETOED
    with reverts():
        voting.vote(alice, 0, 5000, 10000, sender=deployer)

def test_execute(chain, genesis, deployer, alice, bob, executor, voting, token):
    # passed proposals can be executed
    token.mint(executor, 2 * UNIT, sender=deployer)
    script = executor.script(token, token.transfer.encode_input(deployer, UNIT))
    voting.propose(IPFS_HASH, script, sender=alice).return_value

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    voting.vote(alice, 0, 5000, 10000, sender=deployer)

    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    chain.mine()

    assert voting.status(0) == PASSED
    assert not voting.proposals(0).executed
    assert token.balanceOf(deployer) == 0
    voting.execute(0, script, sender=bob)
    assert voting.status(0) == EXECUTED
    assert voting.proposals(0).executed
    assert token.balanceOf(deployer) == UNIT

    with reverts():
        # cant execute more than once
        voting.execute(0, script, sender=bob)

def test_execute_fake(chain, genesis, deployer, alice, bob, executor, voting, token):
    # passed proposals need the right script
    token.mint(executor, 2 * UNIT, sender=deployer)
    script = executor.script(token, token.transfer.encode_input(deployer, UNIT))
    voting.propose(IPFS_HASH, script, sender=alice).return_value

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    voting.vote(alice, 0, 5000, 10000, sender=deployer)

    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    chain.mine()

    with reverts():
        voting.execute(0, executor.script(token, token.transfer.encode_input(deployer, 2 * UNIT)), sender=bob)

    voting.execute(0, script, sender=bob)

def test_execute_failed(chain, genesis, deployer, alice, bob, executor, voting, token):
    # failed proposals cant be executed
    voting.set_threshold(6000, sender=deployer)
    token.mint(executor, 2 * UNIT, sender=deployer)
    script = executor.script(token, token.transfer.encode_input(deployer, UNIT))
    voting.propose(IPFS_HASH, script, sender=alice).return_value

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    voting.vote(alice, 0, 5000, 5999, sender=deployer)

    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    chain.mine()

    assert voting.status(0) == FAILED
    with reverts():
        voting.execute(0, script, sender=bob)

def test_execute_no_votes(chain, genesis, deployer, alice, bob, executor, voting, token):
    # proposals without votes cant be executed
    voting.set_threshold(6000, sender=deployer)
    token.mint(executor, 2 * UNIT, sender=deployer)
    script = executor.script(token, token.transfer.encode_input(deployer, UNIT))
    voting.propose(IPFS_HASH, script, sender=alice).return_value

    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    chain.mine()

    assert voting.status(0) == FAILED
    with reverts():
        voting.execute(0, script, sender=bob)

def test_execute_vetoed(chain, genesis, deployer, alice, bob, executor, voting, token):
    # vetoed proposals cant be executed
    token.mint(executor, 2 * UNIT, sender=deployer)
    script = executor.script(token, token.transfer.encode_input(deployer, UNIT))
    voting.set_guardian(alice, sender=deployer)
    voting.accept_guardian(sender=alice)
    voting.propose(IPFS_HASH, script, sender=alice).return_value

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    voting.vote(alice, 0, 5000, 10000, sender=deployer)

    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    chain.mine()

    assert voting.status(0) == PASSED
    voting.veto(0, ".", sender=alice)
    assert voting.status(0) == VETOED
    
    with reverts():
        voting.execute(0, script, sender=bob)

def test_execute_early(chain, genesis, deployer, alice, bob, executor, voting, token):
    # proposals cant be executed before the delay
    token.mint(executor, 2 * UNIT, sender=deployer)
    script = executor.script(token, token.transfer.encode_input(deployer, UNIT))
    voting.set_execute_parameters(10, False, executor, sender=deployer)
    voting.propose(IPFS_HASH, script, sender=alice).return_value

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    voting.vote(alice, 0, 5000, 10000, sender=deployer)

    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    chain.mine()

    assert voting.status(0) == PASSED
    with reverts():
        voting.execute(0, script, sender=bob)

    chain.pending_timestamp += 10
    voting.execute(0, script, sender=bob)
    assert token.balanceOf(deployer) == UNIT

def test_execute_late(chain, genesis, deployer, alice, bob, executor, voting, token):
    # proposals cant be executed after the epoch is over
    token.mint(executor, 2 * UNIT, sender=deployer)
    script = executor.script(token, token.transfer.encode_input(deployer, UNIT))
    voting.propose(IPFS_HASH, script, sender=alice).return_value

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    voting.vote(alice, 0, 5000, 10000, sender=deployer)

    chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
    chain.mine()

    assert voting.status(0) == EXPIRED
    with reverts():
        voting.execute(0, script, sender=bob)

def test_execute_guard(chain, genesis, deployer, alice, bob, executor, voting, token):
    # proposals cant only be executed by the operator if guard is enabled
    token.mint(executor, 2 * UNIT, sender=deployer)
    script = executor.script(token, token.transfer.encode_input(deployer, UNIT))
    voting.set_operator(bob, sender=deployer)
    voting.set_execute_parameters(0, True, executor, sender=deployer)
    voting.propose(IPFS_HASH, script, sender=alice).return_value

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    voting.vote(alice, 0, 5000, 10000, sender=deployer)

    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    chain.mine()

    assert voting.status(0) == PASSED
    with reverts():
        voting.execute(0, script, sender=alice)

    voting.execute(0, script, sender=bob)
    assert token.balanceOf(deployer) == UNIT

def test_execute_empty(chain, genesis, deployer, alice, voting):
    # proposals without a script dont need to be executed
    voting.propose(IPFS_HASH, b"", sender=alice).return_value

    chain.pending_timestamp = genesis + 5 * EPOCH_LENGTH // 2
    voting.vote(alice, 0, 5000, 10000, sender=deployer)

    chain.pending_timestamp = genesis + 3 * EPOCH_LENGTH
    chain.mine()

    assert voting.status(0) == PASSED

    chain.pending_timestamp = genesis + 4 * EPOCH_LENGTH
    chain.mine()

    assert voting.status(0) == EXECUTED
