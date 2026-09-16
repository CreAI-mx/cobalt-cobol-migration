       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCOUNT-LOOKUP.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCT-FILE ASSIGN TO "accounts.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD ACCT-FILE.
       01 ACCT-RECORD.
           05 ACCT-NUM         PIC 9(10).
           05 ACCT-NAME        PIC X(30).
           05 ACCT-BALANCE     PIC S9(7)V99.

       WORKING-STORAGE SECTION.
       01 WS-SEARCH-NUM        PIC 9(10).
       01 WS-FOUND             PIC X VALUE "N".

       PROCEDURE DIVISION.
           DISPLAY "ENTER ACCOUNT NUMBER: "
           ACCEPT WS-SEARCH-NUM

           OPEN INPUT ACCT-FILE

           PERFORM UNTIL WS-FOUND = "Y"
               READ ACCT-FILE
                   AT END EXIT PERFORM
               END-READ

               IF ACCT-NUM = WS-SEARCH-NUM
                   DISPLAY "ACCOUNT FOUND:"
                   DISPLAY "NAME: " ACCT-NAME
                   DISPLAY "BALANCE: " ACCT-BALANCE
                   MOVE "Y" TO WS-FOUND
               END-IF
           END-PERFORM

           IF WS-FOUND = "N"
               DISPLAY "ACCOUNT NOT FOUND."
           END-IF

           CLOSE ACCT-FILE
           STOP RUN.
