"""Operator commands, run from the backend directory against DATABASE_URL:

    python -m app.cli create-user --email admin@dealer.com --role ADMIN
    python -m app.cli reset-password --email admin@dealer.com
    python -m app.cli list-users
    python -m app.cli reset-data

reset-data deletes every call and all AI data (transcripts, complaints,
escalations, learning evidence and improvements) but keeps user accounts,
so a test environment can start fresh. It refuses to run in production.

The password is asked for interactively, or read from the environment
variable named by --password-env (for scripted deployments). It is never
taken as a command-line argument, where it would end up in shell history.
"""

import argparse
import getpass
import os
import sys

from sqlalchemy import text

from app.composition.database import build_production_repositories
from app.core.config import get_settings
from app.infrastructure.database import models as _models  # noqa: F401  (registers tables)
from app.infrastructure.database.base import Base
from app.infrastructure.database.engine import build_engine
from app.domain.user import UserRole
from app.services.auth_service import AuthService, EmailAlreadyRegisteredError
from app.services.user_management_service import (
    UserManagementError,
    UserManagementService,
    normalize_email,
)


def _password(args: argparse.Namespace) -> str:
    if args.password_env:
        value = os.environ.get(args.password_env, "")
        if not value:
            sys.exit(f"Environment variable {args.password_env} is empty or not set.")
        return value
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return first


# Never cleared by reset-data.
KEPT_TABLES = frozenset({"users"})


def tables_to_reset() -> list[str]:
    return [table.name for table in Base.metadata.sorted_tables if table.name not in KEPT_TABLES]


def _reset_data(confirmed: bool) -> None:
    settings = get_settings()
    if settings.is_production:
        sys.exit("Refusing to reset data with APP_ENV=production.")
    tables = tables_to_reset()
    print("This permanently deletes all rows from:")
    for name in tables:
        print(f"  {name}")
    print("User accounts are kept.")
    if not confirmed and input("Type 'reset' to continue: ").strip() != "reset":
        sys.exit("Cancelled; nothing was deleted.")
    quoted = ", ".join(f'"{name}"' for name in tables)
    with build_engine(settings).begin() as connection:
        connection.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY"))
    print(f"Cleared {len(tables)} tables. Restart the backend to clear in-memory live state.")


def _service() -> UserManagementService:
    repository = build_production_repositories().user
    return UserManagementService(repository, AuthService(repository))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-user", help="Create a user.")
    create.add_argument("--email", required=True)
    create.add_argument("--role", choices=[r.value for r in UserRole], default="ICR")
    create.add_argument("--password-env", help="Read the password from this variable.")

    reset = commands.add_parser("reset-password", help="Set a new password for a user.")
    reset.add_argument("--email", required=True)
    reset.add_argument("--password-env", help="Read the password from this variable.")

    commands.add_parser("list-users", help="List users.")

    reset_data = commands.add_parser(
        "reset-data", help="Delete all calls and AI data, keeping user accounts."
    )
    reset_data.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    args = parser.parse_args(argv)
    if args.command == "reset-data":
        _reset_data(args.yes)
        return 0
    service = _service()

    try:
        if args.command == "create-user":
            user = service.create_user(args.email, _password(args), UserRole(args.role))
            print(f"Created {user.role.value} {user.email} ({user.user_id}).")
        elif args.command == "reset-password":
            email = normalize_email(args.email)
            user = next((u for u in service.list_users() if u.email.lower() == email), None)
            if user is None:
                sys.exit(f"No user with email {email}.")
            service.reset_password(user.user_id, _password(args), acting_user=user)
            print(f"Password updated for {user.email}.")
        else:
            for user in service.list_users():
                state = "active" if user.is_active else "inactive"
                print(f"{user.email}\t{user.role.value}\t{state}\t{user.user_id}")
    except (EmailAlreadyRegisteredError, UserManagementError) as exc:
        sys.exit(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
