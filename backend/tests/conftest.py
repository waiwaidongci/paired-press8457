import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DB = os.path.join(tempfile.mkdtemp(prefix='paired-press-test-'), 'test.db')
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + _DB)
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/15')
os.environ.setdefault('JWT_SECRET', 'test-secret-not-for-production')
