"""Command-driven synthetic storage model. Never imports the reconciler."""
import copy
import hashlib

ESCROW = 'synthetic-escrow'
TOKEN = 'synthetic-token'

def block_hash(number):
    return '0x' + hashlib.sha256(f'synthetic-block-{number}'.encode()).hexdigest()

class Model:
    def __init__(self):
        self.bounties = {}
        self.credits = {}
        self.total_locked = 0
        self.total_claimable = 0
        self.balance = 0
        self.events = []
        self.block = 0
        self.attempts = []

    def emit(self, name, args, actor, source=ESCROW):
        self.block += 1
        self.events.append(dict(event=name, args=args, actor=actor, source=source,
                                block_number=self.block, block_hash=block_hash(self.block),
                                log_index=0, tx_hash=block_hash(self.block + 1000000)))

    def create(self, bid, creator, reward, deadline):
        if bid in self.bounties or type(reward) is not int or reward <= 0:
            raise ValueError('invalid funding')
        self.bounties[bid] = dict(creator=creator, reward=reward, deadline=deadline, status='open')
        self.total_locked += reward
        self.balance += reward
        self.emit('BountyCreated', dict(bountyId=bid, creator=creator, reward=reward,
                  deadline=deadline, briefHash=block_hash(bid), briefURI='local://brief'), creator)
        self.emit('Transfer', {'from': creator, 'to': ESCROW, 'value': reward}, creator, TOKEN)

    def award(self, bid, winner, actor):
        b = self.bounties[bid]
        if actor != b['creator'] or b['status'] != 'open':
            raise ValueError('unauthorized or closed')
        amount = b['reward']
        b['status'] = 'awarded'
        self.total_locked -= amount
        self.total_claimable += amount
        self.credits[winner] = self.credits.get(winner, 0) + amount
        self.emit('BountyAwarded', dict(bountyId=bid, winner=winner, amount=amount), actor)

    def expire(self, bid, now):
        b = self.bounties[bid]
        if now <= b['deadline'] + 604800:
            raise ValueError('too early')
        if b['status'] != 'open':
            raise ValueError('closed')
        amount = b['reward']
        b['status'] = 'expired'
        self.total_locked -= amount
        self.total_claimable += amount
        self.credits[b['creator']] = self.credits.get(b['creator'], 0) + amount
        self.emit('BountyRefunded', dict(bountyId=bid, creator=b['creator'], amount=amount, status=3), b['creator'])

    def withdraw(self, account, recipient, fail=False):
        amount = self.credits.get(account, 0)
        if amount <= 0:
            raise ValueError('no credit')
        storage = copy.deepcopy((self.credits, self.total_claimable, self.balance, self.events, self.block))
        self.credits[account] = 0
        self.total_claimable -= amount
        try:
            if fail:
                raise RuntimeError('simulated token transfer revert')
            self.balance -= amount
            self.emit('Withdrawn', dict(account=account, recipient=recipient, amount=amount), account)
            self.emit('Transfer', {'from': ESCROW, 'to': recipient, 'value': amount}, account, TOKEN)
        except RuntimeError as exc:
            transient = self.credits[account]
            self.credits, self.total_claimable, self.balance, self.events, self.block = storage
            self.attempts.append(dict(account=account, amount=amount, success=False,
                transient_credit=transient, restored_credit=self.credits[account], reason=str(exc), receipt_events=0))
            return False
        self.attempts.append(dict(account=account, amount=amount, success=True, receipt_events=2))
        return True

    def donate(self, donor, amount):
        if type(amount) is not int or amount <= 0:
            raise ValueError('invalid donation')
        self.balance += amount
        self.emit('Transfer', {'from': donor, 'to': ESCROW, 'value': amount}, donor, TOKEN)

    def snapshot(self):
        return dict(block_number=self.block, block_hash=block_hash(self.block),
                    locked={str(k): v['reward'] if v['status']=='open' else 0 for k,v in self.bounties.items()},
                    credits=dict(self.credits), total_locked=self.total_locked,
                    total_claimable=self.total_claimable,
                    liabilities=self.total_locked+self.total_claimable, token_balance=self.balance)
