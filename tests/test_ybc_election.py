from ape import reverts
from pytest import fixture

EPOCH_LENGTH = 14 * 24 * 60 * 60
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

@fixture
def hooks(project, deployer):
    return project.MockYBCMemberHooks.deploy(sender=deployer)

@fixture
def ybc(project, deployer, alice, bob, hooks):
    ybc = project.YBC.deploy(sender=deployer)
    ybc.set_operator(deployer, True, sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(alice), sender=deployer)
    ybc.call(ybc, ybc.add_member.encode_input(bob), sender=deployer)
    ybc.set_hooks(hooks, sender=deployer)
    return ybc

@fixture
def aggregator(project, deployer, alice, bob):
    aggregator = project.MockWeightAggregator.deploy(sender=deployer)
    aggregator.set_weight(alice, UNIT, sender=deployer)
    aggregator.set_weight(bob, 2 * UNIT, sender=deployer)
    return aggregator

@fixture
def election(chain, project, deployer, genesis, ybc, aggregator):
    chain.pending_timestamp = genesis
    election = project.YBCElection.deploy(genesis, ybc, sender=deployer)
    election.set_weight_aggregator(aggregator, sender=deployer)
    election.set_thresholds(5000, 6000, sender=deployer)
    ybc.set_operator(election, True, sender=deployer)
    return election

def test_propose_addition(alice, charlie, election):
    # members can propose an addition
    assert election.num_proposals() == 0
    assert election.status(0) == INVALID
    assert election.propose_addition(charlie, sender=alice).return_value == 0
    assert election.num_proposals() == 1
    assert election.status(0) == PROPOSED
    assert election.proposals(0) == (charlie, alice, 1, True, 5000, 0, 0, False, False)

def test_propose_addition_duplicate(alice, bob, charlie, election):
    # cant propose addition of existing members
    with reverts():
        election.propose_addition(bob, sender=alice)
    election.propose_addition(charlie, sender=alice)

def test_propose_addition_permission(alice, charlie, election):
    # only members can propose an addition
    with reverts():
        election.propose_addition(charlie, sender=charlie)
    election.propose_addition(charlie, sender=alice)

def test_propose_expulsion(alice, bob, election):
    # members can propose an expulsion
    assert election.num_proposals() == 0
    assert election.status(0) == INVALID
    assert election.propose_expulsion(bob, sender=alice).return_value == 0
    assert election.num_proposals() == 1
    assert election.status(0) == PROPOSED
    assert election.proposals(0) == (bob, alice, 1, False, 6000, 0, 0, False, False)

def test_propose_expulsion_invalid(alice, bob, charlie, election):
    # cant propose expulsion of non-members
    with reverts():
        election.propose_expulsion(charlie, sender=alice)
    election.propose_expulsion(bob, sender=alice)

def test_propose_expulsion_permission(alice, bob, charlie, election):
    # only members can propose an expulsion
    with reverts():
        election.propose_expulsion(bob, sender=charlie)
    election.propose_expulsion(bob, sender=alice)

def test_retract_addition(alice, charlie, election):
    # proposers can retract additions in the same epoch
    election.propose_addition(charlie, sender=alice)
    assert election.status(0) == PROPOSED
    election.retract(0, sender=alice)
    assert election.proposals(0) == (charlie, alice, 1, True, 5000, 0, 0, True, False)
    assert election.status(0) == RETRACTED

def test_retract_addition(alice, bob, election):
    # proposers can retract expulsions in the same epoch
    election.propose_expulsion(bob, sender=alice)
    assert election.status(0) == PROPOSED
    election.retract(0, sender=alice)
    assert election.proposals(0) == (bob, alice, 1, False, 6000, 0, 0, True, False)
    assert election.status(0) == RETRACTED

def test_retract_late(chain, alice, charlie, election):
    # proposers can only retract proposals in the same epoch
    election.propose_addition(charlie, sender=alice)
    
    chain.pending_timestamp += EPOCH_LENGTH
    with reverts():
        election.retract(0, sender=alice)

def test_retract_permission(alice, charlie, election):
    # only proposers can retract proposals in the same epoch
    election.propose_addition(charlie, sender=alice)
    with reverts():
        election.retract(0, sender=charlie)
    election.retract(0, sender=alice)

def test_vote_yea(chain, alice, bob, charlie, genesis, election):
    # YBC members can vote in favor of proposals
    election.propose_addition(charlie, sender=alice)

    assert not election.voted(alice, 0)
    assert election.proposals(0).votes == 0
    assert election.proposals(0).yea == 0

    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH - 100
    chain.mine()
    assert election.status(0) == VOTING

    election.vote_yea(0, sender=alice)
    assert election.voted(alice, 0)
    assert election.proposals(0).votes == UNIT
    assert election.proposals(0).yea == UNIT

    assert not election.voted(bob, 0)
    election.vote_yea(0, sender=bob)
    assert election.voted(bob, 0)
    assert election.proposals(0).votes == 3 * UNIT
    assert election.proposals(0).yea == 3 * UNIT

def test_vote_nay(chain, alice, bob, charlie, genesis, election):
    # YBC members can vote against proposals
    election.propose_addition(charlie, sender=alice)

    assert not election.voted(alice, 0)
    assert election.proposals(0).votes == 0
    assert election.proposals(0).yea == 0
    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH - 100
    election.vote_nay(0, sender=alice)
    assert election.voted(alice, 0)
    assert election.proposals(0).votes == UNIT
    assert election.proposals(0).yea == 0

    assert not election.voted(bob, 0)
    election.vote_nay(0, sender=bob)
    assert election.voted(bob, 0)
    assert election.proposals(0).votes == 3 * UNIT
    assert election.proposals(0).yea == 0

def test_vote_multiple(chain, alice, charlie, genesis, election):
    # YBC members cant vote more than once
    election.propose_addition(charlie, sender=alice)

    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH - 100
    election.vote_yea(0, sender=alice)
    with reverts():
        election.vote_yea(0, sender=alice)

def test_vote_early(chain, alice, charlie, genesis, election):
    # YBC members cant vote before second week of next epoch
    election.propose_addition(charlie, sender=alice)

    assert not election.voted(alice, 0)
    assert election.proposals(0).votes == 0
    assert election.proposals(0).yea == 0
    ts = genesis + EPOCH_LENGTH * 3 // 2 - 1
    chain.pending_timestamp = ts
    with reverts():
        election.vote_yea(0, sender=alice)

    chain.pending_timestamp = ts + 1
    election.vote_yea(0, sender=alice)

def test_vote_late(chain, alice, charlie, genesis, election):
    # YBC members cant vote after next epoch
    election.propose_addition(charlie, sender=alice)

    assert not election.voted(alice, 0)
    assert election.proposals(0).votes == 0
    assert election.proposals(0).yea == 0
    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH
    with reverts():
        election.vote_yea(0, sender=alice)

def test_vote_retracted(chain, alice, charlie, genesis, election):
    # YBC members cant vote on retracted proposals
    election.propose_addition(charlie, sender=alice)
    election.retract(0, sender=alice)

    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH - 100
    with reverts():
        election.vote_yea(0, sender=alice)

def test_vote_self_expulsion(chain, alice, bob, genesis, election):
    # YBC members cant vote on their own expulsion
    election.propose_expulsion(bob, sender=alice)

    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH - 100
    with reverts():
        election.vote_nay(0, sender=bob)
    election.vote_nay(0, sender=alice)

def test_addition_passed(chain, deployer, alice, bob, charlie, genesis, aggregator, election):
    # proposals with enough votes in favor pass
    election.propose_addition(charlie, sender=alice)

    aggregator.set_weight(alice, UNIT, sender=deployer)
    aggregator.set_weight(bob, UNIT, sender=deployer)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    # 50% -> passed
    election.vote_yea(0, sender=alice)
    election.vote_nay(0, sender=bob)
    
    chain.pending_timestamp = ts
    chain.mine()
    assert election.status(0) == PASSED

    chain.pending_timestamp += EPOCH_LENGTH
    chain.mine()
    assert election.status(0) == EXPIRED

def test_addition_failed(chain, deployer, alice, bob, charlie, genesis, aggregator, election):
    # proposals with not enough votes in favor fail
    election.propose_addition(charlie, sender=alice)

    aggregator.set_weight(alice, UNIT, sender=deployer)
    aggregator.set_weight(bob, UNIT + 1, sender=deployer)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    # 50% - 1 -> failed
    election.vote_yea(0, sender=alice)
    election.vote_nay(0, sender=bob)

    chain.pending_timestamp = ts
    chain.mine()
    assert election.status(0) == FAILED

    chain.pending_timestamp += EPOCH_LENGTH
    chain.mine()
    assert election.status(0) == FAILED

def test_addition_no_votes(chain, alice, charlie, genesis, election):
    # proposals without votes fail
    election.propose_addition(charlie, sender=alice)

    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH
    chain.mine()
    assert election.status(0) == FAILED

    chain.pending_timestamp += EPOCH_LENGTH
    chain.mine()
    assert election.status(0) == FAILED

def test_expulsion_passed(chain, deployer, alice, bob, charlie, genesis, ybc, aggregator, election):
    # proposals with enough votes in favor pass
    ybc.call(ybc, ybc.add_member.encode_input(charlie), sender=deployer)
    election.propose_expulsion(charlie, sender=alice)

    aggregator.set_weight(alice, 6 * UNIT, sender=deployer)
    aggregator.set_weight(bob, 4 * UNIT, sender=deployer)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    # 60% -> passed
    election.vote_yea(0, sender=alice)
    election.vote_nay(0, sender=bob)
    
    chain.pending_timestamp = ts
    chain.mine()
    assert election.status(0) == PASSED

    chain.pending_timestamp += EPOCH_LENGTH
    chain.mine()
    assert election.status(0) == EXPIRED

def test_expulsion_failed(chain, deployer, alice, bob, charlie, genesis, ybc, aggregator, election):
    # proposals with not enough votes in favor fail
    ybc.call(ybc, ybc.add_member.encode_input(charlie), sender=deployer)
    election.propose_expulsion(charlie, sender=alice)

    aggregator.set_weight(alice, 6 * UNIT, sender=deployer)
    aggregator.set_weight(bob, 4 * UNIT + 1, sender=deployer)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    # 60% - 1 -> failed
    election.vote_yea(0, sender=alice)
    election.vote_nay(0, sender=bob)

    chain.pending_timestamp = ts
    chain.mine()
    assert election.status(0) == FAILED

    chain.pending_timestamp += EPOCH_LENGTH
    chain.mine()
    assert election.status(0) == FAILED

def test_expulsion_no_votes(chain, deployer, alice, charlie, genesis, ybc, election):
    # proposals without votes fail
    ybc.call(ybc, ybc.add_member.encode_input(charlie), sender=deployer)
    election.propose_expulsion(charlie, sender=alice)

    chain.pending_timestamp = genesis + 2 * EPOCH_LENGTH
    chain.mine()
    assert election.status(0) == FAILED

    chain.pending_timestamp += EPOCH_LENGTH
    chain.mine()
    assert election.status(0) == FAILED

def test_execute_addition(chain, deployer, alice, bob, charlie, genesis, hooks, ybc, aggregator, election):
    # passed addition proposals can be executed
    election.propose_addition(charlie, sender=alice)
    aggregator.set_weight(alice, UNIT, sender=deployer)
    aggregator.set_weight(bob, UNIT, sender=deployer)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    election.vote_yea(0, sender=alice)
    election.vote_nay(0, sender=bob)
    
    chain.pending_timestamp = ts
    chain.mine()
    assert election.status(0) == PASSED
    assert not election.proposals(0).executed
    assert not ybc.members(charlie)
    assert hooks.last_add() == ZERO_ADDRESS
    election.execute(0, sender=charlie)
    assert election.status(0) == EXECUTED
    assert election.proposals(0).executed
    assert ybc.members(charlie)
    assert hooks.last_add() == charlie

def test_execute_addition_threshold(chain, deployer, alice, bob, charlie, genesis, aggregator, election):
    # failed addition proposals cant be executed
    election.propose_addition(charlie, sender=alice)
    aggregator.set_weight(alice, UNIT, sender=deployer)
    aggregator.set_weight(bob, UNIT + 1, sender=deployer)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    election.vote_yea(0, sender=alice)
    election.vote_nay(0, sender=bob)
    
    chain.pending_timestamp = ts
    chain.mine()
    assert election.status(0) == FAILED
    with reverts():
        election.execute(0, sender=charlie)

def test_execute_expulsion(chain, deployer, alice, bob, charlie, genesis, hooks, ybc, aggregator, election):
    # passed expulsion proposals can be executed
    ybc.call(ybc, ybc.add_member.encode_input(charlie), sender=deployer)
    election.propose_expulsion(charlie, sender=alice)
    aggregator.set_weight(alice, 6 * UNIT, sender=deployer)
    aggregator.set_weight(bob, 4 * UNIT, sender=deployer)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    election.vote_yea(0, sender=alice)
    election.vote_nay(0, sender=bob)
    
    chain.pending_timestamp = ts
    chain.mine()
    assert election.status(0) == PASSED
    assert not election.proposals(0).executed
    assert ybc.members(charlie)
    assert hooks.last_remove() == ZERO_ADDRESS
    election.execute(0, sender=charlie)
    assert election.status(0) == EXECUTED
    assert election.proposals(0).executed
    assert not ybc.members(charlie)
    assert hooks.last_remove() == charlie

def test_execute_expulsion_threshold(chain, deployer, alice, bob, charlie, genesis, ybc, aggregator, election):
    # failed expulsion proposals cant be executed
    ybc.call(ybc, ybc.add_member.encode_input(charlie), sender=deployer)
    election.propose_expulsion(charlie, sender=alice)
    aggregator.set_weight(alice, 6 * UNIT, sender=deployer)
    aggregator.set_weight(bob, 4 * UNIT + 1, sender=deployer)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    election.vote_yea(0, sender=alice)
    election.vote_nay(0, sender=bob)
    
    chain.pending_timestamp = ts
    chain.mine()
    assert election.status(0) == FAILED
    with reverts():
        election.execute(0, sender=charlie)

def test_execute_double(chain, deployer, alice, charlie, genesis, ybc, election):
    # proposals cant be executed more than once
    election.propose_addition(charlie, sender=alice)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    election.vote_yea(0, sender=alice)

    chain.pending_timestamp = ts
    election.execute(0, sender=charlie)

    ybc.call(ybc, ybc.remove_member.encode_input(charlie), sender=deployer)
    with reverts():
        election.execute(0, sender=charlie)

def test_execute_early(chain, alice, charlie, genesis, election):
    # proposals cant be executed before the epoch is over
    election.propose_addition(charlie, sender=alice)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    election.vote_yea(0, sender=alice)
    assert election.status(0) == VOTING
    with reverts():
        election.execute(0, sender=charlie)

    chain.pending_timestamp = ts
    election.execute(0, sender=charlie)

def test_execute_late(chain, alice, charlie, genesis, election):
    # proposals cant be executed after the next epoch is over
    election.propose_addition(charlie, sender=alice)

    ts = genesis + 2 * EPOCH_LENGTH
    chain.pending_timestamp = ts - 100
    chain.mine()

    election.vote_yea(0, sender=alice)
    
    chain.pending_timestamp = ts + EPOCH_LENGTH
    chain.mine()
    assert election.status(0) == EXPIRED
    with reverts():
        election.execute(0, sender=charlie)