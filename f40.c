#include<stdio.h>

int main()
{
    int len;
    printf("enter the length of array:\n");
    scanf("%d",&len);

    int arr1[len];
    for(int i=0;i<len;i++)
    {
        printf("enter nos.\n");
        scanf("%d",&arr1[i]);
    }
  
    for(int i=len-1;i>-1;i--)
    {
        printf("%d\t",arr1[i]);
    }
    
    
    return 0;
}