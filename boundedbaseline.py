"""Direct-delivery control: identical bounded evidence and draft, without repair."""
import sys
import boundedrun


def main(argv=None):
    return boundedrun.main(['run', *(sys.argv[1:] if argv is None else argv)], with_repair=False)


if __name__ == '__main__':
    main()
