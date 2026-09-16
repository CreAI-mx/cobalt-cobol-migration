       IDENTIFICATION DIVISION.
       PROGRAM-ID. AML-FLAGGING.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TR-AMOUNT        PIC S9(7)V99.
       01 TR-COUNTRY       PIC X(20).
       01 TR-FLAG          PIC X VALUE "N".

       PROCEDURE DIVISION.
           DISPLAY "ENTER TRANSACTION AMOUNT: "
           ACCEPT TR-AMOUNT

           DISPLAY "ENTER COUNTRY: "
           ACCEPT TR-COUNTRY

           IF TR-AMOUNT > 10000
               MOVE "Y" TO TR-FLAG
           END-IF

           IF TR-COUNTRY = "HIGH-RISK"
               MOVE "Y" TO TR-FLAG
           END-IF

           IF TR-FLAG = "Y"
               DISPLAY "AML ALERT: TRANSACTION REQUIRES REVIEW."
           ELSE
               DISPLAY "NO AML FLAGS DETECTED."
           END-IF

           STOP RUN.

