#!/usr/bin/env python3
"""
ChatWithDB - A CLI application for executing MySQL queries interactively.
Supports both natural language queries (via LLM) and direct SQL queries.
"""

import mysql.connector
import argparse
import getpass
import sys
import os
import re
from pathlib import Path
from typing import Optional, Tuple
from mysql.connector import Error
from mysql.connector.cursor import MySQLCursor

# Try to load .env file
try:
    from dotenv import load_dotenv
    # Load .env file from the same directory as the script
    env_path = Path(__file__).parent / '.env'
    load_dotenv(dotenv_path=env_path)
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


def get_groq_api_key() -> Optional[str]:
    """
    Get GROQ_API_KEY from .env file or environment variable.
    Checks in this order:
    1. .env file (production-ready)
    2. Environment variable (backup)
    
    Returns:
        API key if found, None otherwise
    """
    # First, try to get from environment (may be loaded from .env by dotenv)
    api_key = os.environ.get("GROQ_API_KEY")
    
    if api_key:
        # Strip whitespace and quotes
        api_key = api_key.strip().strip('"').strip("'")
        if api_key:
            return api_key
    
    return None


def check_env_file() -> Tuple[bool, str]:
    """
    Check if .env file exists and contains GROQ_API_KEY.
    
    Returns:
        Tuple of (exists, message)
    """
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        try:
            # Try to read and check if GROQ_API_KEY is in it
            with open(env_path, 'r') as f:
                content = f.read()
                if 'GROQ_API_KEY' in content:
                    return True, f".env file exists and contains GROQ_API_KEY"
                else:
                    return True, f".env file exists but GROQ_API_KEY not found in it"
        except Exception as e:
            return True, f".env file exists but couldn't read it: {str(e)}"
    else:
        return False, ".env file not found"


class DatabaseConnection:
    """Handles database connection and query execution."""
    
    def __init__(self, host: str, user: str, password: str, database: str, ssl_disabled: bool = True):
        """Initialize database connection parameters."""
        self.host = host
        self.user = user
        self.database = database
        self.password = password
        self.ssl_disabled = ssl_disabled
        self.connection: Optional[mysql.connector.MySQLConnection] = None
        self.cursor: Optional[MySQLCursor] = None
    
    def connect(self) -> bool:
        """Establish database connection."""
        try:
            print(f"Connecting to MySQL database '{self.database}' at {self.host}...")
            self.connection = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database,
                ssl_disabled=self.ssl_disabled
            )
            
            if self.connection.is_connected():
                print("✓ Successfully connected to the database!")
                self.cursor = self.connection.cursor()
                return True
            else:
                print("✗ Failed to establish connection.")
                return False
                
        except Error as e:
            print(f"✗ Error connecting to MySQL database: {e}")
            return False
        except Exception as e:
            print(f"✗ Unexpected error: {e}")
            return False
    
    def execute_query(self, query: str) -> Tuple[bool, Optional[list], Optional[str]]:
        """Execute a SQL query and return results."""
        if not self.connection:
            return False, None, "Not connected to database. Please reconnect."
        
        try:
            # Check connection status
            if not self.connection.is_connected():
                # Try to reconnect
                try:
                    self.connection.reconnect(attempts=1, delay=0)
                    self.cursor = self.connection.cursor()
                except:
                    return False, None, "Database connection lost. Please restart the application."
            
            # Validate query
            if not query or not query.strip():
                return False, None, "Query cannot be empty."
            
            # Execute query
            self.cursor.execute(query)
            
            # Check if query produces results (SELECT statements)
            if self.cursor.description:
                results = self.cursor.fetchall()
                columns = [desc[0] for desc in self.cursor.description]
                return True, (columns, results), None
            else:
                # For INSERT, UPDATE, DELETE, etc.
                self.connection.commit()
                affected_rows = self.cursor.rowcount
                return True, affected_rows, None
                
        except Error as e:
            # Rollback on error for transactional queries
            try:
                self.connection.rollback()
            except:
                pass
            error_msg = str(e)
            # Provide more user-friendly error messages
            if "Table" in error_msg and "doesn't exist" in error_msg:
                return False, None, f"Table not found: {error_msg}"
            elif "Unknown column" in error_msg:
                return False, None, f"Column not found: {error_msg}"
            elif "Access denied" in error_msg:
                return False, None, f"Permission denied: {error_msg}"
            else:
                return False, None, f"SQL Error: {error_msg}"
        except Exception as e:
            # Rollback on error
            try:
                self.connection.rollback()
            except:
                pass
            return False, None, f"Unexpected error: {str(e)}"
    
    def get_schema_info(self) -> str:
        """Get database schema information for LLM context."""
        if not self.connection or not self.connection.is_connected():
            return f"Database: {self.database}\n(No connection available)"
        
        try:
            schema_info = []
            schema_info.append(f"Database: {self.database}\n")
            
            # Get all tables
            self.cursor.execute("SHOW TABLES")
            tables = self.cursor.fetchall()
            
            if not tables:
                schema_info.append("No tables found in this database.")
                return "\n".join(schema_info)
            
            schema_info.append(f"Tables: {len(tables)}\n")
            
            for (table_name,) in tables:
                schema_info.append(f"\nTable: {table_name}")
                
                try:
                    # Get table structure
                    self.cursor.execute(f"DESCRIBE {table_name}")
                    columns = self.cursor.fetchall()
                    
                    schema_info.append("Columns:")
                    for col in columns:
                        col_name, col_type, null, key, default, extra = col
                        col_info = f"  - {col_name}: {col_type}"
                        if null == 'YES':
                            col_info += " (NULL)"
                        else:
                            col_info += " (NOT NULL)"
                        if key:
                            col_info += f" [{key}]"
                        if extra:
                            col_info += f" {extra}"
                        schema_info.append(col_info)
                    
                    # Get sample data count
                    try:
                        self.cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                        count = self.cursor.fetchone()[0]
                        schema_info.append(f"  Rows: {count}")
                    except Error:
                        schema_info.append("  Rows: (unable to count)")
                        
                except Error as e:
                    schema_info.append(f"  (Error retrieving table structure: {str(e)})")
                    continue
            
            return "\n".join(schema_info)
        except Error as e:
            return f"Database: {self.database}\nError retrieving schema: {str(e)}"
        except Exception as e:
            return f"Database: {self.database}\nUnexpected error: {str(e)}"
    
    def disconnect(self):
        """Close database connection."""
        try:
            if self.cursor:
                self.cursor.close()
            if self.connection and self.connection.is_connected():
                self.connection.close()
                print("\n✓ Database connection closed.")
        except Error as e:
            print(f"✗ Error closing connection: {e}")


class NaturalLanguageQuery:
    """Handles natural language to SQL conversion using LLM."""
    
    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        """Initialize the LLM client."""
        if not GROQ_AVAILABLE:
            raise ImportError(
                "Groq library is not installed. Please install it using: pip install groq"
            )
        
        # Get API key from .env file or environment variable
        api_key = get_groq_api_key()
        if not api_key:
            env_exists, env_msg = check_env_file()
            if env_exists and "contains GROQ_API_KEY" in env_msg:
                raise ValueError(
                    "GROQ_API_KEY found in .env file but is empty or invalid. "
                    "Please check your .env file and ensure it contains: GROQ_API_KEY=your-api-key"
                )
            else:
                raise ValueError(
                    "GROQ_API_KEY is not set. Please set it in one of these ways:\n"
                    "  1. Create a .env file in the project directory with: GROQ_API_KEY=your-api-key\n"
                    "  2. Or set environment variable: export GROQ_API_KEY='your-api-key'"
                )
        
        self.client = Groq(api_key=api_key)
        self.model = model
    
    def natural_language_to_sql(self, user_query: str, schema_info: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Convert natural language query to SQL using LLM."""
        try:
            # Validate user query
            if not user_query or not user_query.strip():
                return False, None, "Query cannot be empty."
            
            # Create a comprehensive prompt for the LLM
            system_prompt = """You are a SQL expert. Your task is to convert natural language queries into valid MySQL SQL queries.

Rules:
1. Generate ONLY the SQL query, nothing else
2. Do not include any explanations, comments, or markdown formatting
3. The query should be executable directly
4. Use proper MySQL syntax
5. If the query is ambiguous, make reasonable assumptions
6. For SELECT queries, always use appropriate WHERE clauses if filtering is mentioned
7. Return only the SQL query, no prefix or suffix
8. Use backticks (`) for table and column names if they contain special characters
9. Always use the database schema provided to ensure table and column names are correct

Database Schema:
""" + (schema_info if schema_info else "No schema information available.") + """

Important: Return ONLY the SQL query without any additional text, explanations, or code blocks."""
            
            user_prompt = f"Convert the following natural language query to MySQL SQL:\n\n{user_query}"
            
            # Call the LLM with timeout handling
            try:
                chat_completion = self.client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    model=self.model,
                    temperature=0.1,  # Lower temperature for more consistent SQL generation
                    max_tokens=500,  # Limit response length
                )
            except Exception as api_error:
                error_msg = str(api_error)
                if "401" in error_msg or "authentication" in error_msg.lower():
                    return False, None, "Authentication failed. Please check your GROQ_API_KEY."
                elif "429" in error_msg or "rate limit" in error_msg.lower():
                    return False, None, "Rate limit exceeded. Please wait a moment and try again."
                elif "network" in error_msg.lower() or "connection" in error_msg.lower():
                    return False, None, "Network error. Please check your internet connection."
                else:
                    return False, None, f"API error: {error_msg}"
            
            # Extract SQL query from response
            if not chat_completion or not chat_completion.choices:
                return False, None, "Empty response from LLM. Please try again."
            
            raw_response = chat_completion.choices[0].message.content.strip()
            
            if not raw_response:
                return False, None, "LLM returned an empty response. Please try rephrasing your question."
            
            # Clean up the SQL query (remove markdown code blocks if present)
            sql_query = raw_response
            
            # Strategy: Extract SQL from markdown code blocks or use raw response
            # First, try to extract from markdown code blocks
            lines = raw_response.split('\n')
            cleaned_lines = []
            in_code_block = False
            
            for line in lines:
                stripped = line.strip()
                # Check for code block markers (```sql or ```)
                if stripped.startswith('```'):
                    # Toggle code block state
                    in_code_block = not in_code_block
                    continue
                
                # If we're in a code block, keep the line (it's SQL)
                # If we're not in a code block but line is not empty, also keep it (might be plain SQL)
                if stripped:
                    cleaned_lines.append(stripped)
            
            # Join lines, preserving structure for multi-line SQL
            if cleaned_lines:
                sql_query = '\n'.join(cleaned_lines).strip()
            else:
                # Fallback: use raw response
                sql_query = raw_response.strip()
            
            # Remove any remaining markdown artifacts at the start/end only
            # Be careful not to remove backticks that are part of SQL identifiers
            if sql_query.startswith('```'):
                # Remove opening markdown marker
                if sql_query.startswith('```sql'):
                    sql_query = sql_query[6:].lstrip()
                elif sql_query.startswith('```'):
                    sql_query = sql_query[3:].lstrip()
            
            if sql_query.endswith('```'):
                # Remove closing markdown marker
                sql_query = sql_query[:-3].rstrip()
            
            sql_query = sql_query.strip()
            
            # Basic validation - ensure query is not empty
            if not sql_query:
                return False, None, f"LLM generated an empty SQL query. Raw response was: {repr(raw_response[:200])}"
            
            # Basic validation - ensure it looks like SQL
            sql_upper = sql_query.upper().strip()
            sql_keywords = ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'SHOW', 'DESCRIBE', 'EXPLAIN', 'USE']
            if not any(sql_upper.startswith(keyword) for keyword in sql_keywords):
                return False, None, f"Generated query doesn't appear to be valid SQL. Received: {sql_query[:100]}"
            
            return True, sql_query, None
            
        except ImportError as e:
            return False, None, f"Groq library not available: {str(e)}"
        except ValueError as e:
            return False, None, f"Configuration error: {str(e)}"
        except Exception as e:
            error_type = type(e).name
            return False, None, f"Error converting to SQL ({error_type}): {str(e)}"


def get_credentials_interactive() -> Tuple[str, str, str, str]:
    """Get database credentials interactively from user."""
    print("Please enter your database credentials:")
    host = input("Host [localhost]: ").strip() or "localhost"
    user = input("User [root]: ").strip() or "root"
    password = getpass.getpass("Password: ")
    database = input("Database: ").strip()
    
    if not database:
        print("✗ Database name is required!")
        sys.exit(1)
    
    return host, user, password, database


def print_results(columns: list, results: list):
    """Pretty print query results."""
    if not results:
        print("Query executed successfully. No rows returned.")
        return
    
    # Calculate column widths
    col_widths = [len(str(col)) for col in columns]
    for row in results:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    
    # Print header
    header = " | ".join(str(col).ljust(col_widths[i]) for i, col in enumerate(columns))
    print(header)
    print("-" * len(header))
    
    # Print rows
    for row in results:
        row_str = " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row))
        print(row_str)
    
    print(f"\n({len(results)} row(s) returned)")


def print_affected_rows(affected_rows: int):
    """Print number of affected rows for non-SELECT queries."""
    print(f"Query executed successfully. {affected_rows} row(s) affected.")


def select_query_mode() -> str:
    """Let user select between SQL and natural language mode."""
    print("\n" + "="*60)
    print("ChatWithDB - Query Mode Selection")
    print("="*60)
    print("Select query mode:")
    print("  1. Direct SQL Queries (enter SQL directly)")
    print("  2. Natural Language Queries (converted to SQL via LLM)")
    print("="*60)
    
    while True:
        choice = input("\nEnter your choice (1 or 2): ").strip()
        if choice == "1":
            return "sql"
        elif choice == "2":
            return "natural_language"
        else:
            print("✗ Invalid choice. Please enter 1 or 2.")


def interactive_mode_natural_language(db: DatabaseConnection, nlq: NaturalLanguageQuery, schema_info: str):
    """Run interactive natural language query execution loop."""
    print("\n" + "="*60)
    print("ChatWithDB - Natural Language Query Mode (Option 2)")
    print("="*60)
    print("Enter your queries in natural language. They will be converted to SQL automatically.")
    print("Type 'quit' or 'exit' to exit.")
    print("Type 'help' for available commands.")
    print("Type 'switch' to switch to SQL mode (Option 1).\n")
    
    while True:
        try:
            # Get query input
            user_query = input("Query> ").strip()
            
            if not user_query:
                continue
            
            # Handle special commands
            if user_query.lower() in ['quit', 'exit', 'q']:
                break
            elif user_query.lower() == 'switch':
                return "switch"
            elif user_query.lower() == 'help':
                print("\nAvailable commands:")
                print("  help          - Show this help message")
                print("  quit/exit/q   - Exit the application")
                print("  switch        - Switch to SQL mode (Option 1)")
                print("  Natural language query - Convert to SQL and execute")
                print("\nExample queries:")
                print("  'Show me all startups'")
                print("  'Count the number of startups in each industry'")
                print("  'Find startups with funding greater than 1000000'")
                print()
                continue
            elif user_query.lower().startswith('clear') or user_query.lower().startswith('cls'):
                print("\n" * 2)
                continue
            
            # Convert natural language to SQL
            print("\n🔄 Converting to SQL...")
            success, sql_query, error = nlq.natural_language_to_sql(user_query, schema_info)
            
            if not success:
                print(f"✗ Error: {error}")
                print()
                continue
            
            print(f"📝 Generated SQL: {sql_query}\n")
            
            # Execute the SQL query
            print("⚡ Executing query...\n")
            success, result, error = db.execute_query(sql_query)
            
            if success:
                if isinstance(result, tuple):
                    # SELECT query with results
                    columns, rows = result
                    print_results(columns, rows)
                else:
                    # Non-SELECT query
                    print_affected_rows(result)
            else:
                print(f"✗ Error executing query: {error}")
            
            print()  # Empty line for readability
            
        except KeyboardInterrupt:
            print("\n\nInterrupted by user. Type 'quit' to exit.")
        except EOFError:
            print("\n\nExiting...")
            break
    
    return "quit"


def interactive_mode_sql(db: DatabaseConnection):
    """Run interactive SQL query execution loop."""
    print("\n" + "="*60)
    print("ChatWithDB - SQL Query Mode (Option 1)")
    print("="*60)
    print("Enter your SQL queries directly.")
    print("Type 'quit' or 'exit' to exit.")
    print("Type 'help' for available commands.")
    print("Type 'switch' to switch to Natural Language mode (Option 2).\n")
    
    while True:
        try:
            # Get query input
            query = input("SQL> ").strip()
            
            if not query:
                continue
            
            # Handle special commands
            if query.lower() in ['quit', 'exit', 'q']:
                break
            elif query.lower() == 'switch':
                return "switch"
            elif query.lower() == 'help':
                print("\nAvailable commands:")
                print("  help          - Show this help message")
                print("  quit/exit/q   - Exit the application")
                print("  switch        - Switch to Natural Language mode (Option 2)")
                print("  Any SQL query - Execute the SQL query")
                print()
                continue
            elif query.lower().startswith('clear') or query.lower().startswith('cls'):
                print("\n" * 2)
                continue
            
            # Execute query
            success, result, error = db.execute_query(query)
            
            if success:
                if isinstance(result, tuple):
                    # SELECT query with results
                    columns, rows = result
                    print_results(columns, rows)
                else:
                    # Non-SELECT query
                    print_affected_rows(result)
            else:
                print(f"✗ Error: {error}")
            
            print()  # Empty line for readability
            
        except KeyboardInterrupt:
            print("\n\nInterrupted by user. Type 'quit' to exit.")
        except EOFError:
            print("\n\nExiting...")
            break
    
    return "quit"


def interactive_mode(db: DatabaseConnection, use_natural_language: bool = False):
    """Run interactive query execution loop with mode selection."""
    # Initialize natural language query handler if needed
    nlq = None
    schema_info = ""
    schema_loaded = False
    
    if use_natural_language:
        try:
            if not GROQ_AVAILABLE:
                print("⚠ Natural Language mode not available. Groq library not installed.")
                print("   Install it using: pip install groq")
                use_natural_language = False
            else:
                # Check for API key (from .env or environment)
                api_key = get_groq_api_key()
                if not api_key:
                    env_exists, env_msg = check_env_file()
                    print("⚠ Natural Language mode not available. GROQ_API_KEY not found.")
                    print("\n   To enable it:")
                    print("   1. Create a .env file in the project directory:")
                    print("      echo 'GROQ_API_KEY=your-api-key' > .env")
                    print("   2. Or set environment variable:")
                    print("      export GROQ_API_KEY='your-api-key'")
                    use_natural_language = False
                else:
                    try:
                        nlq = NaturalLanguageQuery()
                        print("✓ Natural Language mode available (using Groq API)")
                        # Get schema info for LLM context
                        schema_info = db.get_schema_info()
                        if schema_info and "Error" not in schema_info:
                            print("✓ Database schema loaded for better query generation")
                            schema_loaded = True
                        elif schema_info:
                            print("⚠ Schema information may be incomplete")
                            schema_loaded = True
                        else:
                            print("⚠ No schema information available")
                    except ValueError as e:
                        print(f"⚠ Natural Language mode not available: {e}")
                        use_natural_language = False
                    except ImportError as e:
                        print(f"⚠ Natural Language mode not available: {e}")
                        use_natural_language = False
                    except Exception as e:
                        print(f"⚠ Error initializing Natural Language mode: {str(e)}")
                        use_natural_language = False
                        nlq = None
        except Exception as e:
            print(f"⚠ Unexpected error: {str(e)}")
            use_natural_language = False
    
    # If natural language is not available, default to SQL mode
    if not use_natural_language or not nlq:
        use_natural_language = False
    
    current_mode = "natural_language" if use_natural_language else "sql"
    
    while True:
        if current_mode == "natural_language":
            if not nlq:
                print("⚠ Natural Language mode is not available. Switching to SQL mode.")
                current_mode = "sql"
                continue
            result = interactive_mode_natural_language(db, nlq, schema_info)
            if result == "quit":
                break
            elif result == "switch":
                current_mode = "sql"
                continue
        else:
            result = interactive_mode_sql(db)
            if result == "quit":
                break
            elif result == "switch":
                if nlq:
                    # Reload schema if needed
                    if not schema_loaded:
                        schema_info = db.get_schema_info()
                        schema_loaded = True
                    current_mode = "natural_language"
                    continue
                else:
                    print("\n⚠ Natural Language mode is not available.")
                    print("   To enable it:")
                    print("   1. Install: pip install groq python-dotenv")
                    print("   2. Create .env file: echo 'GROQ_API_KEY=your-api-key' > .env")
                    print("   Continuing in SQL mode...\n")
                    continue


def main():
    """Main entry point for the CLI application."""
    parser = argparse.ArgumentParser(
        description='ChatWithDB - Interactive MySQL query CLI tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --host localhost --user root --database mydb
  %(prog)s --host localhost --user root --database mydb --password
  %(prog)s  # Interactive mode (prompts for all credentials)
        """
    )
    
    parser.add_argument('--host', '-H', 
                       help='MySQL server host (default: localhost)',
                       default=None)
    parser.add_argument('--user', '-u',
                       help='MySQL username (default: root)',
                       default=None)
    parser.add_argument('--password', '-p',
                       help='Prompt for password (always prompted for security)',
                       action='store_true')
    parser.add_argument('--database', '-d',
                       help='Database name (required)',
                       default=None)
    parser.add_argument('--ssl-disabled',
                       help='Disable SSL connection',
                       action='store_true',
                       default=True)
    
    args = parser.parse_args()
    
    # Get credentials
    if args.database:
        # Command-line mode
        host = args.host or "localhost"
        user = args.user or "root"
        password = getpass.getpass("Password: ")
        database = args.database
    else:
        # Interactive mode
        host, user, password, database = get_credentials_interactive()
    
    # Create database connection
    db = DatabaseConnection(host, user, password, database, args.ssl_disabled)
    
    # Connect to database
    if not db.connect():
        print("\n✗ Failed to connect to database. Please check your credentials and try again.")
        sys.exit(1)
    
    # Check if natural language mode is available with detailed diagnostics
    groq_installed = GROQ_AVAILABLE
    api_key = get_groq_api_key()
    api_key_set = api_key is not None
    env_exists, env_msg = check_env_file()
    dotenv_available = DOTENV_AVAILABLE
    
    # Detailed diagnostics
    print("\n" + "="*60)
    print("System Diagnostics")
    print("="*60)
    print(f"Groq library installed: {'✓ Yes' if groq_installed else '✗ No'}")
    print(f"python-dotenv available: {'✓ Yes' if dotenv_available else '✗ No (install: pip install python-dotenv)'}")
    print(f".env file status: {env_msg}")
    print(f"GROQ_API_KEY found: {'✓ Yes' if api_key_set else '✗ No'}")
    if api_key_set:
        # Show first and last few characters for security
        key_preview = api_key[:10] + "..." + api_key[-10:] if len(api_key) > 20 else "*"
        print(f"API Key preview: {key_preview}")
        # Show source
        if env_exists and Path(__file__).parent / '.env':
            print(f"API Key source: .env file (production-ready)")
        else:
            print(f"API Key source: Environment variable")
    print("="*60)
    
    natural_language_available = groq_installed and api_key_set
    
    # Let user select query mode
    if natural_language_available:
        selected_mode = select_query_mode()
        use_natural_language = (selected_mode == "natural_language")
    else:
        # Show menu but only SQL mode is available with specific issues
        print("\n" + "="*60)
        print("ChatWithDB - Query Mode Selection")
        print("="*60)
        print("Select query mode:")
        print("  1. Direct SQL Queries (enter SQL directly)")
        
        if not groq_installed and not api_key_set:
            print("  2. Natural Language Queries (⚠ Not available)")
            print("="*60)
            print("\n⚠ Natural Language mode is not available.")
            print("\nIssues found:")
            print("  ✗ Groq library is not installed")
            print("  ✗ GROQ_API_KEY is not set")
            env_exists, env_msg = check_env_file()
            print(f"  .env file: {env_msg}")
            print("\nTo enable Natural Language mode:")
            print("  1. Install dependencies:")
            print("     pip install groq python-dotenv")
            print("     OR if using venv:")
            print("     source venv/bin/activate")
            print("     pip install groq python-dotenv")
            print("\n  2. Create a .env file (recommended for production):")
            print("     echo 'GROQ_API_KEY=your-api-key' > .env")
            print("     # Or edit .env file and add: GROQ_API_KEY=your-api-key")
            print("\n  Alternative (for development):")
            print("  3. Set environment variable:")
            print("     export GROQ_API_KEY='your-api-key'")
            print("\n  4. Verify and restart this application")
        elif not groq_installed:
            print("  2. Natural Language Queries (⚠ Not available - Groq not installed)")
            print("="*60)
            print("\n⚠ Natural Language mode is not available.")
            print("\nIssue found:")
            print("  ✗ Groq library is not installed")
            print("\nTo enable Natural Language mode:")
            print("  1. Install groq:")
            print("     pip install groq")
            print("     OR if using venv:")
            print("     source venv/bin/activate")
            print("     pip install groq")
            print("  2. Restart this application")
        elif not api_key_set:
            print("  2. Natural Language Queries (⚠ Not available - API key not set)")
            print("="*60)
            print("\n⚠ Natural Language mode is not available.")
            print("\nIssue found:")
            print("  ✗ GROQ_API_KEY is not set")
            env_exists, env_msg = check_env_file()
            print(f"  .env file: {env_msg}")
            print("\nTo enable Natural Language mode (recommended for production):")
            print("  1. Create a .env file in the project directory:")
            print("     echo 'GROQ_API_KEY=your-api-key' > .env")
            print("     # Or edit .env file and add: GROQ_API_KEY=your-api-key")
            print("\n  Alternative (for development):")
            print("  2. Set environment variable:")
            print("     export GROQ_API_KEY='your-api-key'")
            print("     # Note: No spaces around the = sign!")
            print("\n  3. Install python-dotenv (if not installed):")
            print("     pip install python-dotenv")
            print("\n  4. Verify and restart this application")
        else:
            print("  2. Natural Language Queries (⚠ Not available)")
            print("="*60)
            print("\n⚠ Natural Language mode is not available.")
        
        print()
        
        while True:
            choice = input("Enter your choice (1): ").strip()
            if choice == "1":
                use_natural_language = False
                break
            elif choice == "2":
                print("\n✗ Natural Language mode is not available. Please see the issues above.")
                print("   Fix the issues and restart the application, or select option 1 for SQL mode.\n")
                continue
            else:
                print("✗ Invalid choice. Please enter 1.")
        
        print("\n✓ Using SQL mode.\n")
    
    # Run interactive mode
    try:
        interactive_mode(db, use_natural_language=use_natural_language)
    finally:
        db.disconnect()


if __name__ == "__main__":
    main()