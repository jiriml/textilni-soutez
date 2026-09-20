# Textilni Soutez


## Setup Instructions

Follow the steps below depending on your operating system.


## Windows Setup

Copy and run these commands in **Command Prompt or PowerShell**:

```bash
git clone https://github.com/jiriml/textilni-soutez.git
cd textilni-soutez

python -m venv venv
.\venv\Scripts\activate

pip install -r requirements.txt

python app.py
```

## Linux/MacOS Setup
Copy and run these commands in **whatever command line you use**:
```bash

git clone https://github.com/jiriml/textilni-soutez.git
cd textilni-soutez

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

python3 app.py
```
## Note
Or you can just set up your own virtual enviroment in your IDE.

## Voting configuration

Set `MAX_VOTES_PER_USER` in `.env` to control how many different designs one
user may select. The default is `1`.

```env
MAX_VOTES_PER_USER=3
```

The admin panel controls the competition mode:

- `designing`: users see only their own designs and can upload/delete designs.
- `voting`: users see all designs and can vote, but regular users do not see vote counts.
- `finished`: everyone sees vote counts; uploading, voting, and deleting are disabled.