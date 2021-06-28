

To set up the EC2 instance:
1. Create an EC2 machine using your AWS account.
2. Create a policy for EC2 machine : 

  a.  Go to your IAM dashboard : ![image](https://user-images.githubusercontent.com/68659873/123625727-ad722900-d82d-11eb-9c22-6d6548cb1c44.png)
  b. Create a new policy in `Customer Managed policies` : ![image](https://user-images.githubusercontent.com/68659873/123625940-e7dbc600-d82d-11eb-8a91-883a8a5b24c5.png)
  c. Add JSON policy : ![image](https://user-images.githubusercontent.com/68659873/123626293-502aa780-d82e-11eb-969d-c185eb72b1e7.png)
  
   The policy :
   ```json
   {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "VisualEditor0",
            "Effect": "Allow",
            "Action": "ec2:*",
            "Resource": "*"
        }
    ]
   }
   ```
  d. Add the policy to the role : ![image](https://user-images.githubusercontent.com/68659873/123626422-781a0b00-d82e-11eb-8a88-a81020eadbd6.png)
![image](https://user-images.githubusercontent.com/68659873/123626504-8d8f3500-d82e-11eb-93f4-86b8fc596701.png)


3. SSH into the EC2 Instance.
4. Setup `serverless` on the instance: 
   ```python
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.34.0/install.sh | bash
    . ~/.nvm/nvm.sh
    nvm install node
    npm install -g serverless
   ```
5. Setup `docker` on the instance:
   ```python
    sudo yum install -y docker
    sudo service docker start
    sudo usermod -a -G docker ec2-user 
   ```
6. Logout and login again so that docker daemon starts.
7. Install SSM Agent : `sudo yum install -y https://s3.eu-west-1.amazonaws.com/amazon-ssm-eu-west-1/latest/linux_amd64/amazon-ssm-agent.rpm`
8. Use WinSCP or FileZilla to set up the `ec2_script` at `/home/ec2-user/automation/`
9. You're good to go!
