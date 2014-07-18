/**
 * @fileOverview New user page JS
 * @requires AngularJS
 *
 */

// New user page includes the User Editor editor
angular.module('UserNew', ['UserEditor'])
    .controller('UserNewCtrl', function ($scope, $http) {
        $scope.form = $('#user-new-form');
        $scope.submitEndpoint = '';
        $scope.allUsersRedirect = '';
        $scope.singleUserRedirect = '';
        $scope.quotas_expanded = false;
        $scope.adv_expanded = false;
        $scope.ec2_expanded = false;
        $scope.s3_expanded = false;
        $scope.autoscale_expanded = false;
        $scope.elb_expanded = false;
        $scope.iam_expanded = false;
        $scope.isNotValid = true;
        $scope.toggleQuotasContent = function () {
            $scope.quotas_expanded = !$scope.quotas_expanded;
        };
        $scope.toggleAdvContent = function () {
            $scope.adv_expanded = !$scope.adv_expanded;
        };
        $scope.toggleEC2Content = function () {
            $scope.ec2_expanded = !$scope.ec2_expanded;
        };
        $scope.toggleS3Content = function () {
            $scope.s3_expanded = !$scope.s3_expanded;
        };
        $scope.toggleAutoscaleContent = function () {
            $scope.autoscale_expanded = !$scope.autoscale_expanded;
        };
        $scope.toggleELBContent = function () {
            $scope.elb_expanded = !$scope.elb_expanded;
        };
        $scope.toggleIAMContent = function () {
            $scope.iam_expanded = !$scope.iam_expanded;
        };
        $scope.initController = function(submitEndpoint, allRedirect, singleRedirect, getFileEndpoint) {
            $scope.submitEndpoint = submitEndpoint;
            $scope.allUsersRedirect = allRedirect;
            $scope.singleUserRedirect = singleRedirect;
            $scope.getFileEndpoint = getFileEndpoint;
            $scope.setWatch();
            $('#user-name-field').focus();
        }
        $scope.setWatch = function () {
            $scope.$on('userAdded', function () {
                $scope.isNotValid = false;
            });
            $scope.$on('emptyUsersArray', function () {
                $scope.isNotValid = true;
            });
        };
        $scope.submit = function($event) {
            // Handle the unsaved user issue
            if($('#user-name-field').val() !== ''){
                $event.preventDefault(); 
                $('#unsaved-user-warn-modal').foundation('reveal', 'open');
                return false;
            }
            var form = $($event.target);
            $('#user-list-error').css('display', 'none');
            $('#quota-error').css('display', 'none');
            var users = JSON.parse(form.find('textarea[name="users"]').val())
            var singleUser = Object.keys(users)[0]
            if (singleUser === undefined) {
                $('#user-list-error').css('display', 'block');
                return;
            }
            var invalid = form.find('input[data-invalid]');
            if (invalid.length > 0) {
                $('#quota-error').css('display', 'block');
                return false;
            }
            var isSingleUser = Object.keys(users).length == 1;
            var csrf_token = form.find('input[name="csrf_token"]').val();
            var data = $($event.target).serialize();
            $http({method:'POST', url:$scope.submitEndpoint, data:data,
                   headers: {'Content-Type': 'application/x-www-form-urlencoded'}}).
              success(function(oData) {
                var results = oData ? oData.results : [];
                Notify.success(oData.message);
                if (results.hasFile == 'y') {
                    $('#new_password').val("");
                    $('#new_password2').val("");
                    $('#password-strength').removeAttr('class');
                    $.generateFile({
                        csrf_token: csrf_token,
                        filename: 'not-used', // let the server set this
                        content: 'none',
                        script: $scope.getFileEndpoint
                    });
                    // this is clearly a hack. We'd need to bake callbacks into the generateFile
                    // stuff to do this properly.
                    setTimeout(function() {
                        if (isSingleUser) {
                            window.location = $scope.singleUserRedirect.replace('_name_', singleUser);
                        } else {
                            window.location = $scope.allUsersRedirect;
                        }
                    }, 3000);
                }
                else {
                    if (isSingleUser) {
                        window.location = $scope.singleUserRedirect.replace('_name_', singleUser);
                    } else {
                        window.location = $scope.allUsersRedirect;
                    }
                }
            }).error(function (oData, status) {
                var errorMsg = oData['message'] || '';
                if (errorMsg && status === 403) {
                    $('#timed-out-modal').foundation('reveal', 'open');
                }
                Notify.failure(errorMsg);
            });
        };
    })
;

