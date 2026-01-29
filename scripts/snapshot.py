from ape import Contract, networks
from json import dump, load

YFI = '0x0bc529c00C6401aEF6D220BE8C6Ea1667F6Ad93e'
VEYFI = '0x90c1f9220d90d3966FbeE24045EDd73E1d588aD5'
DEPLOY_HEIGHT = 15974608
SNAPSHOT_HEIGHT = 23460759
SNAPSHOT_TS = 1759053599

GENESIS = 1770249600
WEEK_LENGTH = 7 * 24 * 60 * 60
EPOCH_LENGTH = 2 * WEEK_LENGTH
MAX_LOCK_LENGTH = 4 * 365 * 86400 // WEEK_LENGTH * WEEK_LENGTH

LIQUID_LOCKERS = [
    "0xF750162fD81F9a436d74d737EF6eE8FC08e98220", # StakeDAO
    "0x242521ca01f330F050a65FF5B8Ebbe92198Ae64F", # 1UP
    "0x05dcdBF02F29239D1f8d9797E22589A2DE1C152F", # Cove
]

def main():
    veyfi = Contract(VEYFI)

    # scan events for accounts
    events = veyfi.ModifyLock.query("*", start_block=DEPLOY_HEIGHT, stop_block=-1)
    accounts = set()
    for ev in events["event_arguments"]:
        accounts.add(ev["user"])
    accounts = sorted(accounts)

    # write accounts to json
    file = open("veyfi_accounts.json", "w")
    dump(accounts, file, indent=2)
    file.close()

    # read accounts from json
    file = open("veyfi_accounts.json", "r")
    accounts = load(file)

    # build snapshot
    max_lock_end = SNAPSHOT_TS + MAX_LOCK_LENGTH
    snapshot = []
    for account in accounts:
        amount, end = veyfi.locked(account, block_id=SNAPSHOT_HEIGHT)
        amount_current, end_current = veyfi.locked(account)

        if amount == 0 or end < GENESIS + EPOCH_LENGTH:
            # no lock or expired lock
            continue

        if account in LIQUID_LOCKERS:
            print(f"{account} skipped: liquid locker")
            continue

        if amount > amount_current:
            print(f"{account} skipped: early exited")
            continue

        if end > max_lock_end:
            print(f"{account} has lock longer than 4y")
            end = max_lock_end

        if end > end_current:
            print(f"{account} skipped: lock shortened by too much (relock?)")
            continue

        boost = (end - SNAPSHOT_TS) // EPOCH_LENGTH
        snapshot.append([account, amount, boost, end])

    # write snapshot to json
    file = open("veyfi_snapshot.json", "w")
    dump(list(snapshot), file, indent=2)
    file.close()
