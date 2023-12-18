from pathlib import Path
from typing import Any, Dict, List
import os
import textwrap

import typer
import yaml

from github import Github
from github.Issue import Issue
from github.Repository import Repository

from loguru import logger

DEFAULT_CONFIG = {"owner": "uw-ssec", "repo": "codeuw", "repos": []}


def load_config(config_file: str = ".codeuw-config.yml") -> Dict[str, Any]:
    """
    Load configuration file

    Parameters
    ----------
    config_file : str, optional
        The string path to configuration file,
        by default ".codeuw-config.yml"

    Returns
    -------
    Dict[str, Any]
        The configuration dictionary
    """
    config_path = Path(config_file)
    config = yaml.safe_load(config_path.read_text())

    # Set defaults, in case they're not in the config file
    for key, value in DEFAULT_CONFIG.items():
        config.setdefault(key, value)

    return config


def setup_github() -> Github:
    """
    Setup Github API

    Returns
    -------
    Github
        Github API object
    """
    from github import Auth

    # using an access token
    # it'll look for environment variable GITHUB_TOKEN
    auth = Auth.Token(os.environ.get("GITHUB_TOKEN"))

    # Public Web Github
    return Github(auth=auth)


def parse_issue_template(source_repo: Repository) -> Dict[str, Any]:
    """
    Parse the issue template from the source repository
    and output a dictionary of the template

    Parameters
    ----------
    source_repo : Repository
        The source repository to parse the issue template from

    Returns
    -------
    dict
        The dictionary of the issue template
    """
    issue_template = source_repo.get_contents(path=".github/ISSUE_TEMPLATE/task.yml")
    task_template = yaml.safe_load(issue_template.decoded_content)

    # Create the body markdown template
    body_template = ""
    for input in task_template["body"]:
        input_id = input["id"]
        section_string = textwrap.dedent(
            f'### {input["attributes"]["label"]}\n\n' f"{{{input_id}}}\n\n"
        )
        body_template += section_string

    # Setup the template dictionary
    template_dict = {
        "title": (task_template["title"] + "{project_name} - {title_text}").format,
        "labels": task_template["labels"],
        "body": body_template.format,
    }

    return template_dict


def generate_code_uw_issues(
    issues_with_label: List[Issue],
    template_dict: Dict[str, Any],
    repo: Dict[str, Any],
    source_issue_titles: List[str],
    gh_repo: Repository,
    source_repo: Repository,
    dry_run: bool = False,
) -> None:
    # Loop over issues and create one by one
    for issue in issues_with_label:
        issue_template = template_dict.copy()
        issue_title = issue_template["title"](
            project_name=repo["name"], title_text=issue.title
        )

        # Skip the rest if issue already exists
        if issue_title in source_issue_titles:
            logger.info(f"Issue already exists in source: {issue_title}")
            continue

        issue_template["title"] = issue_title
        issue_template["body"] = issue_template["body"](
            contact="*Please provide your contact information here.*",
            description=issue.body if issue.body else "*No description provided.*",
            repo=gh_repo.html_url,
            issue=issue.html_url,
            level="*Please provide the level of the task here.*",
            language="*Please provide the programming language of the task here.*",
            dependencies="*No response*",
        )

        logger.info(f'Creating issue: {issue_template["title"]}')
        logger.info(f'Labels: {issue_template["labels"]}')
        if not dry_run:
            created_issue = source_repo.create_issue(**issue_template)
            logger.info(f"Issue successfully created: {created_issue.html_url}")
        else:
            logger.info("Dry run, not creating issue. Here is the issue body:\n")
            logger.info("\n" + issue_template["body"])


def main(config_file: str = ".codeuw-config.yml", dry_run: bool = False):
    """
    Loads "codeuw" labeled issues from Github
    """
    g = setup_github()
    config = load_config(config_file=config_file)

    # Get source repo
    source_repo = g.get_repo("/".join([config["owner"], config["repo"]]))

    # Get all issue titles from source repo
    source_issue_titles = [issue.title for issue in source_repo.get_issues(state="all")]

    # Get the template dictionary
    template_dict = parse_issue_template(source_repo)

    for repo in config["repos"]:
        repo_path = "/".join([repo["org"], repo["repo"]])
        gh_repo = g.get_repo(repo_path)
        # Get issues with codeuw label only
        issues_with_label = [
            issue
            for issue in gh_repo.get_issues()
            if "codeuw" in [label.name for label in issue.labels]
        ]
        generate_code_uw_issues(
            issues_with_label,
            template_dict,
            repo,
            source_issue_titles,
            gh_repo,
            source_repo,
            dry_run,
        )


if __name__ == "__main__":
    typer.run(main)
