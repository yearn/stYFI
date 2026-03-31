from ape import reverts, Contract
from pytest import fixture

UNIT = 10**18
PERIOD_LENGTH = 6 * 14 * 24 * 60 * 60
ORACLE_TIMEOUT = 24 * 60 * 60

# the following tests can only be ran with `--network ethereum:mainnet-fork` flag:

# @fixture
# def chainlink():
#     return Contract("0xA027702dbb89fbd58938e4324ac03B58d812b0E1")

# @fixture
# def oracle(chain, project, deployer, chainlink):
#     genesis = chain.pending_timestamp - PERIOD_LENGTH
#     oracle = project.BonusPriceOracle.deploy(genesis, sender=deployer)
#     oracle.set_price_oracle(chainlink, ORACLE_TIMEOUT, 10**10, sender=deployer)
#     return oracle

# def test_chainlink_price(deployer, oracle):
#     assert oracle.period() == 1
#     assert oracle.prices(0) == 0
#     price = oracle.price(0, sender=deployer).return_value
#     assert price > 10**21 and price < 10**22
#     assert oracle.prices(0) == 0

# def test_chainlink_price_write(chain, deployer, alice, oracle):
#     oracle.set_bonus_distributor(alice, sender=deployer)

#     # stale oracle
#     ts = chain.pending_timestamp
#     with chain.isolate():
#         chain.pending_timestamp = ts + ORACLE_TIMEOUT
#         with reverts():
#             oracle.price(0, sender=alice)

#     chain.pending_timestamp = ts
#     assert oracle.prices(0) == 0
#     price = oracle.price(0, sender=alice).return_value
#     assert price > 1_000 * UNIT and price < 10_000 * UNIT
#     assert oracle.prices(0) == price

#     # once written, chainlink oracle is no longer queried
#     chain.pending_timestamp = ts + ORACLE_TIMEOUT
#     assert oracle.price(0, sender=alice).return_value == price

# def test_set_price(deployer, oracle):
#     assert oracle.period() == 1
#     price = 2_000 * UNIT
#     oracle.set_price(0, price, sender=deployer)
#     assert oracle.price(0, sender=deployer).return_value == price
