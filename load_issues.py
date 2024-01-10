from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List
import os
import textwrap
import time

import typer
import yaml
import msgpack

from github import Github
from github import Auth
from github.Issue import Issue
from github.Repository import Repository

from loguru import logger

DEFAULT_CONFIG = {"owner": "uw-ssec", "repo": "codeuw", "repos": []}
DEFAULT_STATE_FILE = ".codeuw-state.mpk"
DEFAULT_CONFIG_FILE = ".codeuw-config.yml"


def load_config(config_file: str = DEFAULT_CONFIG_FILE) -> Dict[str, Any]:
    """
    Load configuration file

    Parameters
    ----------
    config_file : str, optional
        The string path to configuration file

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
    # using an access token
    # it'll look for environment variable GITHUB_TOKEN
    auth = Auth.Token(os.environ.get("GITHUB_TOKEN"))

    # Public Web Github
    return Github(auth=auth)


def parse_issue_template(codeuw_repo: Repository) -> Dict[str, Any]:
    """
    Parse the issue template from the codeuw repository
    and output a dictionary of the template

    Parameters
    ----------
    codeuw_repo : Repository
        The codeuw repository to parse the issue template from

    Returns
    -------
    dict
        The dictionary of the issue template
    """
    issue_template_content_file = codeuw_repo.get_contents(path=".github/ISSUE_TEMPLATE/task.yml")
    issue_template = yaml.safe_load(issue_template_content_file.decoded_content)

    # Create the body markdown template
    body_template = ""
    for input in issue_template["body"]:
        input_id = input["id"]
        section_string = textwrap.dedent(
            f'### {input["attributes"]["label"]}\n\n' f"{{{input_id}}}\n\n"
        )
        body_template += section_string

    # Setup the template dictionary
    template_dict = {
        "title": (issue_template["title"] + "{project_name} - {title_text}").format,
        "labels": issue_template["labels"],
        "body": body_template.format,
    }

    return template_dict


def generate_code_uw_issues(
    issues_with_label: List[Issue],
    template_dict: Dict[str, Any],
    project_name: str,
    codeuw_state: OrderedDict,
    gh_repo: Repository,
    codeuw_repo: Repository,
    dry_run: bool = False,
) -> OrderedDict:
    """Generate codeuw issues from
    the issues with codeuw label

    Parameters
    ----------
    issues_with_label : List[Issue]
        The list of ``Issue`` objects with codeuw label
    template_dict : Dict[str, Any]
        The template dictionary to create issue
    project_name : str
        The repository custom project name from config
    codeuw_state : OrderedDict
        The codeuw state dictionary
    gh_repo : Repository
        The Github repository object to get issues from
    codeuw_repo : Repository
        The Github repository object of the codeuw repo
    dry_run : bool, optional
        Flag to signify a dry run, which doesn't create issues
        within the codeuw repo, by default False
        
    Returns
    -------
    OrderedDict
        The updated codeuw state dictionary
    """
    # Loop over issues and create one by one
    for issue in issues_with_label:
        issue_template = template_dict.copy()
        issue_title = issue_template["title"](
            project_name=project_name, title_text=issue.title
        )
        issue_creator = issue.user.login

        # Skip the rest if issue already exists
        if issue.number in codeuw_state["issues"][gh_repo.full_name]:
            codeuw_issue_number = codeuw_state["issues"][gh_repo.full_name][issue.number]
            logger.info(f"Issue ({gh_repo.full_name}#{issue.number}) already exists in repo: {codeuw_repo.full_name}#{codeuw_issue_number}")
            continue

        issue_template["title"] = issue_title
        issue_template["body"] = issue_template["body"](
            contact=f"@{issue_creator}",
            description=issue.body if issue.body else "*No description provided.*",
            repo=gh_repo.html_url,
            issue=issue.html_url,
            level=f"*@{issue_creator}: Please provide the level of the task here.*",
            language=f"*@{issue_creator}: Please provide the programming language of the task here.*",
            dependencies="*No response*",
        )

        logger.info(f'Creating issue: {issue_template["title"]}')
        logger.info(f'Labels: {issue_template["labels"]}')
        if not dry_run:
            created_issue = codeuw_repo.create_issue(**issue_template)
            logger.info(f"Issue successfully created: {created_issue.html_url}")
            codeuw_state["issues"][gh_repo.full_name][issue.number] = created_issue.number
        else:
            logger.info("Dry run, not creating issue. Here is the issue body:\n")
            logger.info("\n" + issue_template["body"])
            codeuw_state["issues"][gh_repo.full_name][issue.number] = -1
        codeuw_state["last_modified"] = int(time.time())
    return codeuw_state

def get_state(state_file: "str | Path" = DEFAULT_STATE_FILE) -> OrderedDict:
    """
    Get the state dictionary from the state file
    """
    state_file = Path(state_file)
    if state_file.exists():
        # Read the state file when it already exists
        return read_state(state_file=state_file)
    else:
        # If state file doesn't exist, create a new one
        codeuw_state = OrderedDict({
            "version": "1.0",
            "created_time": int(time.time()),
            "last_modified": int(time.time()),
            "issues": {}
        })
        return codeuw_state

def write_state(state_dict: OrderedDict, state_file: "str | Path" = DEFAULT_STATE_FILE) -> None:
    """
    Write state file to disk as messagepack file format
    """
    state_file = Path(state_file)
    state_file.write_bytes(msgpack.packb(state_dict))
    
def read_state(state_file: "str | Path" = DEFAULT_STATE_FILE) -> OrderedDict:
    """
    Read state file from disk as messagepack file format
    """
    state_file = Path(state_file)
    return msgpack.unpackb(state_file.read_bytes(), strict_map_key=False)

def main(config_file: str = DEFAULT_CONFIG_FILE, dry_run: bool = False):
    """
    Loads "codeuw" labeled issues from Github
    """
    gh = setup_github()
    config = load_config(config_file=config_file)

    # Get codeuw repo
    codeuw_repo = gh.get_repo("/".join([config["owner"], config["repo"]]))
    
    # Get the state dictionary
    codeuw_state = get_state()

    # Get the template dictionary
    template_dict = parse_issue_template(codeuw_repo)

    for repo in config["repos"]:
        repo_path = "/".join([repo["org"], repo["repo"]])
        # If repo not in state, add it
        if repo_path not in codeuw_state["issues"]:
            codeuw_state["issues"][repo_path] = {}

        gh_repo = gh.get_repo(repo_path)
        # Get issues with codeuw label only
        issues_with_label = [
            issue
            for issue in gh_repo.get_issues()
            if "codeuw" in [label.name for label in issue.labels]
        ]
        codeuw_state = generate_code_uw_issues(
            issues_with_label,
            template_dict,
            repo['name'],
            codeuw_state,
            gh_repo,
            codeuw_repo,
            dry_run,
        )
    
    if not dry_run:
        logger.info("Writing state file to disk")
        write_state(codeuw_state)
        
    repos_message = []
    for repo, issue_numbers in codeuw_state["issues"].items():
        repos_message.append(f"{repo}: {len(issue_numbers)} issues")
    repos_message_str = "\n".join(repos_message)

    final_message = textwrap.dedent(f"Issues creation summary:\n{repos_message_str}")
    logger.info(final_message)


if __name__ == "__main__":
    typer.run(main)
