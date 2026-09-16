       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRANSACTION-POSTING.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANS-FILE ASSIGN TO "transactions.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT ACCT-FILE ASSIGN TO "accounts.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD TRANS-FILE.
       01 TRANS-RECORD.
           05 TR-ACCT-NUM      PIC 9(10).
           05 TR-AMOUNT        PIC S9(7)V99.
           05 TR-TYPE          PIC X(10).

       FD ACCT-FILE.
       01 ACCT-RECORD.
           05 ACCT-NUM         PIC 9(10).
           05 ACCT-BALANCE     PIC S9(7)V99.

       WORKING-STORAGE SECTION.
       01 WS-EOF               PIC X VALUE "N".

       PROCEDURE DIVISION.
           OPEN INPUT TRANS-FILE
                I-O ACCT-FILE

           PERFORM UNTIL WS-EOF = "Y"
               READ TRANS-FILE
                   AT END MOVE "Y" TO WS-EOF
               END-READ

               IF WS-EOF = "N"
                   PERFORM PROCESS-TRANSACTION
               END-IF
           END-PERFORM

           CLOSE TRANS-FILE ACCT-FILE
           STOP RUN.

       PROCESS-TRANSACTION.
           READ ACCT-FILE
               INVALID KEY DISPLAY "ACCOUNT NOT FOUND: " TR-ACCT-NUM
           END-READ

           IF TR-TYPE = "DEPOSIT"
               ADD TR-AMOUNT TO ACCT-BALANCE
           ELSE IF TR-TYPE = "WITHDRAWAL"
               SUBTRACT TR-AMOUNT FROM ACCT-BALANCE
           END-IF

           REWRITE ACCT-RECORD.
