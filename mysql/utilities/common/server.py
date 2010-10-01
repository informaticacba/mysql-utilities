#
# Copyright (c) 2010, Oracle and/or its affiliates. All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307 USA
#

"""
This module contains an abstraction of a MySQL server object used
by multiple utlities. It also contains helper methods for common
server operations used in multiple utilities.
"""

import os
import re
import sys
import MySQLdb
from mysql.utilities.common import MySQLUtilError

# List of database objects for enumeration
_DATABASE, _TABLE, _VIEW, _TRIG, _PROC, _FUNC, _EVENT, _GRANT = "DATABASE", \
    "TABLE", "VIEW", "TRIGGER", "PROCEDURE", "FUNCTION", "EVENT", "GRANT"

def _print_connection(prefix, conn_val):
    """ Print connection information
    """
    conn_str = None
    sys.stdout.write("# %s on %s: ... " % (prefix, conn_val["host"]))


def connect_servers(src_val, dest_val, silent=False, version=None,
                    src_name="Source", dest_name="Destination"):
    """ Connect to a source and destination server.
    
    This method takes two groups of --server=user:password@host:port:socket
    values and attempts to connect one as a source connection and the other
    as the destination connection. If the source and destination are the
    same server, destination is set to None.
    
    src_val[in]        a dictionary containing connection information for the
                       source including:
                       (user, passwd, host, port, socket)
    dest_val[in]       a dictionary containing connection information for the
                       destination including:
                       (user, passwd, host, port, socket)
    silent[in]         do not print any information during the operation
                       (default is False)
    version[in]        if specified (default is None), perform version
                       checking and fail if server version is < version
                       specified - an exception is raised
    src_name[in]       name to use for source server
                       (default is "Source")
    dest_name[in]      name to use for destination server
                       (default is "Destination")

    Returns tuple (source, destination) where
            source = connection to source server
            destination = connection to destination server (set to None)
                          if source and destination are same server
            if error, returns (None, None)
    """
    source = None
    destination = None
    cloning = (src_val == dest_val) or dest_val is None
    if version is not None:
        major, minor, rel = version.split(".")

    # If we're cloning so use same server for faster copy
    if not cloning and dest_val is None:
        dest_val = src_val
        
    if not silent:
        _print_connection(src_name, src_val)

    # Try to connect to the MySQL database server (source).
    source = Server(src_val, src_name)
    try:
        source.connect()
        if version is not None:
            if not source.check_version_compat(major, minor, rel):
                raise MySQLUtilError("The %s version is incompatible. Utility "
                                     "requires version %s or higher." %
                                     (src_name, version))
    except MySQLUtilError, e:
        raise e
        
    if not silent:
        sys.stdout.write("connected.\n")

    if not silent:
        if not cloning:
            _print_connection(dest_name, dest_val)
        elif dest_val is not None:
            _print_connection(dest_name, src_val)

    if not cloning:
        # Try to connect to the MySQL database server (destination).
        destination = Server(dest_val, "destination")
        try:
            destination.connect()
            if version is not None:
                if not source.check_version_compat(major, minor, rel):
                    raise MySQLUtilError("The %s version is incompatible."
                                         " Utility requires version %s or "
                                         "higher." % (dest_name, version))
        except MySQLUtilError, e:
            raise e
        
    if not silent and dest_val is not None:
        sys.stdout.write("connected.\n")
        
    servers = (source, destination)
    return servers


class Server(object):
    """The Server class can be used to connect to a running MySQL server.
    The following utilities are provided:
    
        - Connect to the server
        - Retrieve a server variable
        - Execute a query
        - Return list of all databases
        - Return a list of specific objects for a database
        - Return list of a specific objects for a database
        - Return list of all indexes for a table
        - Read SQL statements from a file and execute
    """
    
    def __init__(self, conn_val, role="Server", verbose=False):
        """Constructor
        
        dest_val[in]       a dictionary containing connection information
                           (user, passwd, host, port, socket)
        role[in]           Name or role of server (e.g., server, master)
        verbose[in]        print extra data during operations (optional)
                           default value = False
        """
        self.verbose = verbose
        self.db_conn = None
        self.role = role
        self.host = conn_val["host"]
        self.user = conn_val["user"]
        self.passwd = conn_val["passwd"]
        self.socket = conn_val["unix_socket"] if "unix_socket" in conn_val else None
        self.port = 3306
        if conn_val["port"] is not None:
            self.port = int(conn_val["port"])
        self.connect_error = None
        
        
    def __del__(self):
        """Destructor
        
        Closes MySQLdb connections if open.
        """
        if self.db_conn:
            self.db_conn.close()
    
    
    def connect(self):
        """Connect to server
        
        Attempts to connect to the server as specified by the connection
        parameters.
        
        Note: This method must be called before executing queries.

        Raises MySQLUtilError if error during connect
        """
        try:
            parameters = {
                'user': self.user,
                'host': self.host,
                'port': self.port,
                }
            if self.socket:
                parameters['unix_socket'] = self.socket
            if self.passwd and self.passwd != "":
                parameters['passwd'] = self.passwd
            self.db_conn = MySQLdb.connect(**parameters)
        except MySQLdb.Error, e:
            raise MySQLUtilError("Cannot connect to the %s server.\n"
                                 "Error %d: %s" % (self.role,
                                                   e.args[0], e.args[1]))
            return False
        self.connect_error = None


    def get_create_statement(self, db, name, obj_type):
        """Return the create statement for the object
        
        db[in]             Database name
        name[in]           Name of the object 
        obj_type[in]       Object type (string) e.g. DATABASE
                           Note: this is used to form the correct SHOW command
    
        Returns create statement
        """
    
        row = None
        if obj_type == _DATABASE:
            name_str = name
        else:
            name_str = db + "." + name
        try:
            row = self.exec_query("SHOW CREATE %s %s" % (obj_type, name_str))
        except MySQLUtilError, e:
            raise e
        
        create_statement = None
        if row:
            if obj_type == _TABLE or obj_type == _VIEW or \
               obj_type == _DATABASE:
                create_statement = row[0][1]
            elif obj_type == _EVENT:
                create_statement = row[0][3]
            else:
                create_statement = row[0][2]
        if create_statement.find("%"):
            create_statement = re.sub("%", "%%", create_statement)
        return create_statement
        
    def check_version_compat(self, t_major, t_minor, t_rel):
        """ Checks version of the server against requested version.
        
        This method can be used to check for version compatibility.
        
        t_major[in]        target server version (major)
        t_minor[in]        target server version (minor)
        t_rel[in]          target server version (release)

        Returns bool True if server version is GE (>=) version specified,
                     False if server version is LT (<) version specified
        """
        res = self.show_server_variable("VERSION")
        if res:
            version_str = res[0][1]
            index = version_str.find("-")
            if index >= 0:
                parts = res[0][1][0:index].split(".")
            else:
                parts = res[0][1].split(".")
            major = parts[0]
            minor = parts[1]
            rel = parts[2]
            if int(t_major) > int(major):
                return False
            elif int(t_major) == int(major):
                if int(t_minor) > int(minor):
                    return False
                elif int(t_minor) == int(minor):
                    if int(t_rel) > int(rel):
                        return False
        return True
    
    
    def toggle_fkeys(self, turn_on=True):
        """ Turn foreign key checks on or off
        
        turn_on[in]        if True, turns on fkey check
                           if False, turns off fkey check

        Returns original value = True == ON, False == OFF
        """
        
        fkey_query = "SET foreign_key_checks = %s"
        try:
            res = self.show_server_variable("foreign_key_checks")
            fkey = (res[0][1] == "ON")
        except MySQLUtilError, e:
            raise e
        if not fkey and turn_on:
            try:
                res = self.exec_query(fkey_query, "ON")
            except MySQLUtilError, e:
                raise e
        elif fkey and not turn_on:
            try:
                res = self.exec_query(fkey_query, "OFF")
            except MySQLUtilError, e:
                raise e
        return fkey


    def cursor(self):
        """Return the cursor object.
        """

        # Guard for connect() prerequisite
        assert self.db_conn, "You must call connect before executing a query."

        return self.db_conn.cursor()

    
    def exec_query(self, query_str, params=()):
        """Execute a query and return result set
        
        Note: will handle exception and print error if query fails
        
        query_str[in]      The query to execute
        params[in]         Parameters for query 
    
        Returns MySQLdb result set
        """

        # Guard for connect() prerequisite
        assert self.db_conn, "You must call connect before executing a query."
        
        cur = self.db_conn.cursor()
        try:
            cur.execute(query_str, params)
        except MySQLdb.Error, e:
            raise MySQLUtilError("Query failed. %d: %s" %
                                 (e.args[0], e.args[1]))
        except Exception, e:
            raise MySQLUtilError("Unknown error. Command: %s" % query_str)
        results = cur.fetchall()
        cur.close()
        self.db_conn.commit()        
        return results
    
    
    def show_server_variable(self, variable):
        """Returns one or more rows from the SHOW VARIABLES command.
        
        variable[in]       The variable or wildcard string
    
        Returns MySQLdb result set
        """

        return self.exec_query("SHOW VARIABLES LIKE %s", (variable,))


    def get_all_databases(self):
        """Return a result set containing all databases on the server
        except for internal databases (mysql, INFORMATION_SCHEMA,
        PERFORMANCE_SCHEMA)
        
        Returns MySQLdb result set
        """
        
        _GET_DATABASES = """
        SELECT SCHEMA_NAME 
        FROM INFORMATION_SCHEMA.SCHEMATA 
        WHERE SCHEMA_NAME != 'INFORMATION_SCHEMA' 
        AND SCHEMA_NAME != 'PERFORMANCE_SCHEMA' 
        AND SCHEMA_NAME != 'mysql'
        """
        return self.exec_query(_GET_DATABASES)


    def get_db_objects(self, db, obj_type):
        """Return a result set containing all objects for a given database
        
        db[in]             Name of the database
        obj_type[in]       Type of object to retrieve    

        TODO: Change implementation to return classes instead of a result set.
    
        Returns MySQLdb result set
        """
    
        if obj_type == _TABLE:
            _OBJECT_QUERY = """
            SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE <> 'VIEW'
            """
        elif obj_type == _VIEW:
            _OBJECT_QUERY = """
            SELECT TABLE_NAME FROM INFORMATION_SCHEMA.VIEWS 
            WHERE TABLE_SCHEMA = %s
            """
        elif obj_type == _TRIG:
            _OBJECT_QUERY = """
            SELECT TRIGGER_NAME FROM INFORMATION_SCHEMA.TRIGGERS 
            WHERE TRIGGER_SCHEMA = %s 
            """
        elif obj_type == _PROC:
            _OBJECT_QUERY = """
            SELECT ROUTINE_NAME FROM INFORMATION_SCHEMA.ROUTINES 
            WHERE ROUTINE_SCHEMA = %s AND ROUTINE_TYPE = 'PROCEDURE'
            """
        elif obj_type == _FUNC:
            _OBJECT_QUERY = """
            SELECT ROUTINE_NAME FROM INFORMATION_SCHEMA.ROUTINES 
            WHERE ROUTINE_SCHEMA = %s AND ROUTINE_TYPE = 'FUNCTION'
            """
        elif obj_type == _EVENT:
            _OBJECT_QUERY = """
            SELECT EVENT_NAME FROM INFORMATION_SCHEMA.EVENTS 
            WHERE EVENT_SCHEMA = %s
            """
        elif obj_type == _GRANT:
            _OBJECT_QUERY = """
            (
                SELECT grantee AS c1, privilege_type AS c2, table_schema AS c3,
                       NULL AS c4, NULL AS c5, NULL AS c6
                FROM INFORMATION_SCHEMA.SCHEMA_PRIVILEGES 
                WHERE table_schema = %s
            ) UNION (
                SELECT grantee, privilege_type, table_schema, table_name,
                       NULL, NULL 
                FROM INFORMATION_SCHEMA.TABLE_PRIVILEGES 
                WHERE table_schema = %s
            ) UNION (
                SELECT grantee, privilege_type, table_schema, table_name,
                       column_name, NULL 
                FROM INFORMATION_SCHEMA.COLUMN_PRIVILEGES 
                WHERE table_schema = %s
            ) UNION (
                SELECT CONCAT('''', User, '''@''', Host, ''''),  Proc_priv, Db,
                       Routine_name, NULL, Routine_type 
                FROM mysql.procs_priv WHERE Db = %s
            ) ORDER BY c1 ASC, c2 ASC, c3 ASC, c4 ASC, c5 ASC, c6 ASC
            """
        else:
            return None
        
        if obj_type == _GRANT:
            return self.exec_query(_OBJECT_QUERY, (db,db,db,db,))
        else:
            return self.exec_query(_OBJECT_QUERY, (db,))
        

    def read_and_exec_SQL(self, input_file, verbose=False):
        """Read an input file containing SQL statements and execute them.
    
        input_file[in]     The full path to the file
        verbose[in]        Print the command read
                           Default = False

        Returns True = success, False = error
        
        TODO : Make method read multi-line queries.
        """
        file = open(input_file)
        i = 0
        res = True
        while True:
            cmd = file.readline()
            if not cmd:
                break;
            i += 1
            res = None
            if len(cmd) > 1:
                if cmd[0] != '#':
                    if verbose:
                        print cmd
                    try:
                        res = self.exec_query(cmd)
                    except MySQLUtilError, e:
                        raise e
        file.close()
        return res
