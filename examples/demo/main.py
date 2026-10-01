import json
from pathlib import Path


def total():
    with open('assets/values.json', encoding='utf-8') as stream:
        return sum(json.load(stream)['values'])


if __name__ == '__main__':
    assert total() == 6
    print('Total: 6')
