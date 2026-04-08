#include <stdio.h>
#include <string.h>

#define SIZE 5

typedef struct{
    char name[20];
    int id;
    int status;
}Seat;

Seat s[SIZE];

int allEmpty(){
    for(int i=0;i<SIZE;i++)
        if(s[i].status==1) return 0;
    return 1;
}

int full(){
    for(int i=0;i<SIZE;i++)
        if(s[i].status==0) return 0;
    return 1;
}

void listTakenSeat(){
    printf("listTakenSeat():\n");

    if(allEmpty()){
        printf("The seat assignment list is empty\n");
        return;
    }

    for(int i=0;i<SIZE;i++){
        if(s[i].status==1){
            printf("Customer name: %s\n",s[i].name);
            printf("Seat number (ID): %d\n",s[i].id);
        }
    }
}

void assignSeat(){
    int seat;
    char name[20];

    printf("assignSeat():\n");

    if(full()){
        printf("The plane is full\n");
        return;
    }

    printf("Enter the seat number:\n");

    while(1){
        scanf("%d",&seat);

        if(seat<1 || seat>5){
            printf("Please enter a seat number between 1 and 5\n");
            continue;
        }

        if(s[seat-1].status==1){
            printf("Occupied! Please choose another seat\n");
            continue;
        }

        printf("Enter customer name:\n");
        scanf(" %[^\n]",name);

        strcpy(s[seat-1].name,name);
        s[seat-1].status=1;

        printf("The seat has been assigned successfully\n");
        break;
    }
}

void removeSeat(){
    int seat;

    printf("removeSeat():\n");

    if(allEmpty()){
        printf("All the seats are vacant\n");
        return;
    }

    printf("Enter the seat number:\n");

    while(1){
        scanf("%d",&seat);

        if(seat<1 || seat>5){
            printf("Please enter a seat number between 1 and 5\n");
            continue;
        }

        if(s[seat-1].status==0){
            printf("Empty! Enter another seat number for removal\n");
            continue;
        }

        s[seat-1].status=0;
        strcpy(s[seat-1].name,"");

        printf("Removal is successful\n");
        break;
    }
}

int main(){
    int choice;

    for(int i=0;i<SIZE;i++){
        s[i].id=i+1;
        s[i].status=0;
        strcpy(s[i].name,"");
    }

    printf("NTU AIRLINES SEATING RESERVATION PROGRAM:\n");
    printf("1: listTakenSeat()\n");
    printf("2: assignSeat()\n");
    printf("3: removeSeat()\n");
    printf("4: quit\n");

    do{
        printf("Enter your choice:\n");
        scanf("%d",&choice);

        switch(choice){
            case 1: listTakenSeat(); break;
            case 2: assignSeat(); break;
            case 3: removeSeat(); break;
        }

    }while(choice!=4);

    return 0;
}